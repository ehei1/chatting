import argparse
import collections
import concurrent.futures
import logging
import os
import signal
import sys

import grpc
import socket
import typing

from proto import client_to_agent_pb2
from proto import client_to_agent_pb2_grpc


class Channel:
    def __init__(self, address: str, channel_index: int, user_index: int, executor: concurrent.futures.ThreadPoolExecutor):
        self.__address = address
        self.__index = channel_index

        channel = grpc.insecure_channel(address)
        self.__stub = stub = client_to_agent_pb2_grpc.ChannelStub(channel)

        iterator = stub.TryChatReceive(
            client_to_agent_pb2.Chat(index=user_index))
        self.__chat_future = executor.submit(handle_chat_response, iterator)

        iterator = stub.TryStatusRequest(
            client_to_agent_pb2.UserRequest(index=user_index))
        self.__status_future = executor.submit(handle_status_response, iterator)

    @property
    def stub(self) -> client_to_agent_pb2_grpc.ChannelStub:
        return self.__stub

    @property
    def address(self) -> str:
        return self.__address

    @property
    def index(self) -> int:
        return self.__index


def handle_chat_send(
        user_index: int,
        lobby_stub: client_to_agent_pb2_grpc.LobbyStub,
        executor: concurrent.futures.ThreadPoolExecutor) -> None:
    lobby_chat_command = '/all'
    make_channel_command = '/make'
    list_channels_command = '/list'
    join_channel_command = '/join'
    leave_channel_command = '/leave'
    list_users_command = '/user'
    help_command = '/?'
    helps = (
        (lobby_chat_command, 'send chat to all'),
        (make_channel_command, 'make a channel'),
        (list_channels_command, 'list up all channels'),
        (join_channel_command, 'join to channel'),
        (leave_channel_command, 'leave from the channel'),
        (list_users_command, 'list users in the channel or lobby'),
        (help_command, 'list up all commands'),
    )
    helps = collections.OrderedDict(helps)
    channel = None

    print(f'Help: {help_command}')

    while True:
        try:
            text = input()
        except KeyboardInterrupt as e:
            break

        text = text.strip()
        words = text.split()
        command = words[0]

        if command not in helps:
            if channel is None:
                print('You have to join a channel to chat')
            else:
                channel.stub.TryChatSend(client_to_agent_pb2.Chat(index=user_index, text=text))

            continue

        text = ' '.join(words[1:])

        if lobby_chat_command == command:
            lobby_stub.TryChatSend(client_to_agent_pb2.Chat(index=user_index, text=text))
        elif make_channel_command == command:
            if channel is None:
                response = lobby_stub.TryCommand(
                    client_to_agent_pb2.CommandRequest(
                        index=user_index,
                        status=client_to_agent_pb2.CommandRequest.Status.MAKE_CHANNEL))

                if client_to_agent_pb2.CommandReply.Status.SUCCESS == response.status:
                    channel_index = response.channels[0]
                    channel = Channel(response.address, channel_index, user_index, executor)

                    print(f'channel is created:{response.address}')
                elif client_to_agent_pb2.CommandReply.Status.FAILURE == response.status:
                    print('channel creating is failed')
                else:
                    assert False
            else:
                print('you are in a channel already')
        elif list_channels_command == command:
            response = lobby_stub.TryCommand(
                client_to_agent_pb2.CommandRequest(
                    index=user_index,
                    status=client_to_agent_pb2.CommandRequest.Status.LIST_CHANNELS))

            if response.channels:
                for channel in response.channels:
                    print(f'channel:{channel}')
            else:
                print('There is no channel')
        elif join_channel_command == command:
            if channel is not None:
                print('You entered in a channel')
                continue

            try:
                channel_index = int(text)
            except ValueError:
                print('You entered invalid channel')
                continue

            response = lobby_stub.TryCommand(
                client_to_agent_pb2.CommandRequest(
                    status=client_to_agent_pb2.CommandRequest.Status.JOIN_CHANNEL,
                    index=user_index,
                    channel=channel_index))

            if client_to_agent_pb2.CommandReply.Status.SUCCESS == response.status:
                channel = Channel(response.address, channel_index, user_index, executor)

                print(f'You joined at channel {response.address}')
            elif client_to_agent_pb2.CommandReply.Status.FAILURE == response.status:
                print('channel creating is failed')
            else:
                assert False
        elif leave_channel_command == command:
            if channel is None:
                print('It can use when you are in a channel')
                continue

            lobby_stub.TryCommand(
                client_to_agent_pb2.CommandRequest(
                    status=client_to_agent_pb2.CommandRequest.Status.LEAVE_CHANNEL,
                    index=user_index,
                    channel=channel.index))

            print(f'You left from channel {channel.address}')
            channel = None
        elif list_users_command == command:
            try:
                channel_index = int(text)
            except ValueError:
                channel_index = 0

            response = lobby_stub.TryCommand(
                client_to_agent_pb2.CommandRequest(
                    index=user_index,
                    status=client_to_agent_pb2.CommandRequest.Status.LIST_USERS,
                    channel=channel_index))

            if response.users:
                assert len(response.users) == len(response.channels)

                for _user_index, _channel_index in zip(response.users, response.channels):
                    print(f'user:{_user_index} at channel {_channel_index}')
        elif help_command == command:
            for command, description in helps.items():
                print(f'{command}: {description}')
        else:
            assert False


def handle_heartbeat(response_iterator: 'typing.Iterator[client_to_agent_pb2.HeartbeatReply]') -> None:
    for response in response_iterator:
        logging.debug(response.time)


def handle_chat_response(response_iterator: 'typing.Iterator[client_to_agent_pb2.Chat]') -> None:
    for response in response_iterator:
        print(f'{response.index}: {response.text}')


def handle_status_response(
        response_iterator: 'typing.Iterator[client_to_agent_pb2.StatusReply]',
        cancelling_futures = None) -> None:
    for response in response_iterator:
        if response.status == client_to_agent_pb2.StatusReply.Status.JOIN_USER:
            if response.channel:
                print(f'user {response.index} joined at channel {response.channel}')
            else:
                print(f'user {response.index} joined at lobby')
        elif response.status == client_to_agent_pb2.StatusReply.Status.LEAVE_USER:
            if response.channel:
                print(f'user {response.index} left from channel {response.channel}')
            else:
                print(f'user {response.index} left from lobby')
        elif response.status == client_to_agent_pb2.StatusReply.Status.QUIT:
            print("You're checked by late response")
        else:
            assert False


def run() -> None:
    parser = argparse.ArgumentParser(prog='python console.py', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--agent', dest='agent', default='loca'
                                                         'lhost:50050', help='agent address to connect')
    arguments = parser.parse_args()

    with grpc.insecure_channel(arguments.agent) as agent_channel:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)

        agent_stub = client_to_agent_pb2_grpc.AgentStub(agent_channel)
        agent_response = agent_stub.TryLogin(client_to_agent_pb2.LoginRequest(ip=ip_address))

        print(f'my index is {agent_response.index}')

        with grpc.insecure_channel(agent_response.heartbeat_ip) as heartbeat_channel:
            heartbeat_stub = client_to_agent_pb2_grpc.HeartbeatStub(heartbeat_channel)
            heartbeat_response_iterator = heartbeat_stub.TryHeartbeat(
                client_to_agent_pb2.HeartbeatRequest(index=agent_response.index))

            executor = concurrent.futures.ThreadPoolExecutor()
            f0 = executor.submit(handle_heartbeat, heartbeat_response_iterator)

            with grpc.insecure_channel(agent_response.lobby_ip) as lobby_channel:
                lobby_stub = client_to_agent_pb2_grpc.LobbyStub(lobby_channel)
                lobby_response_iterator = lobby_stub.TryChatReceive(
                    client_to_agent_pb2.Chat(index=agent_response.index))
                lobby_status_iterator = lobby_stub.TryStatusRequest(
                    client_to_agent_pb2.UserRequest(index=agent_response.index))

                f1 = executor.submit(handle_chat_response, lobby_response_iterator)
                f2 = executor.submit(handle_chat_send, agent_response.index, lobby_stub, executor)

                cancelling_futures_when_quit = (f0, f1, f2)
                f3 = executor.submit(handle_status_response, lobby_status_iterator, cancelling_futures_when_quit)
                futures = cancelling_futures_when_quit + (f3,)

                concurrent.futures.wait(futures)


if __name__ == '__main__':
    logging.basicConfig()

    run()
