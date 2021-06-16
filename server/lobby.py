import asyncio
import collections
import logging
import time

import grpc

from proto import client_to_agent_pb2
from proto import client_to_agent_pb2_grpc
from server.channel import Channel


class User:
    __time_stamp = 0
    __validating_time = 60

    def __init__(self, index: int):
        self.index = index
        self.chats = []
        self.channel = 0
        self.statuses = []

    def validate(self):
        self.__time_stamp = time.time() + self.__validating_time

    def is_invalidated(self) -> bool:
        return self.__time_stamp < time.time()


class Lobby(client_to_agent_pb2_grpc.Lobby):
    def __init__(self, lobby_address: str, channel_ip: str, channel_ports:'tuple[int]'):
        self.__channels = collections.OrderedDict()
        self.__users = {}
        self.__address = lobby_address
        self.__channel_ports = list(channel_ports)
        self.__channel_ip = channel_ip
        self.__server = server = grpc.aio.server()

        client_to_agent_pb2_grpc.add_LobbyServicer_to_server(self, server)
        server.add_insecure_port(self.__address)

    async def TryChatSend(
            self, request: client_to_agent_pb2.Chat,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Empty:
        if request.text:
            for index in self.__users.keys() - {request.index}:
                self.__users[index].chats.append(request)

            self.__get_user(request.index).validate()

        return client_to_agent_pb2.Empty()

    async def TryChatReceive(
            self, request: client_to_agent_pb2.Chat,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Chat:
        user = self.__get_user(request.index)

        while True:
            if user.chats:
                for chat in user.chats:
                    yield chat

                user.chats.clear()

            await asyncio.sleep(1)

    async def TryUserRemove(
            self, request: client_to_agent_pb2.UserRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Empty:
        if request.index in self.__users:
            user = self.__users.pop(request.index)
            await self.__remove_user_from_channel(user.index, user.channel)

        return client_to_agent_pb2.Empty()

    async def TryCommand(
            self, request: client_to_agent_pb2.CommandRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.CommandReply:
        status = client_to_agent_pb2.CommandRequest.Status

        try:
            user = self.__users[request.index]
        except KeyError:
            logging.info(f'requested user is not: {request.index}')

            return client_to_agent_pb2.CommandReply(status=client_to_agent_pb2.CommandReply.Status.FAILURE)
        else:
            user.validate()

        if status.LIST_CHANNELS == request.status:
            channels = tuple(self.__channels)

            return client_to_agent_pb2.CommandReply(channels=channels)
        elif status.MAKE_CHANNEL == request.status:
            if not self.__channel_ports:
                return client_to_agent_pb2.CommandReply(status=client_to_agent_pb2.CommandReply.Status.FAILURE)

            port = self.__channel_ports.pop(0)
            channel = Channel(self.__channel_ip, port)
            self.__channels[port] = channel
            user.channel = port

            await channel.run()

            return client_to_agent_pb2.CommandReply(
                status=client_to_agent_pb2.CommandReply.Status.SUCCESS,
                address=f'{self.__channel_ip}:{port}',
                channels=(port,))
        elif status.JOIN_CHANNEL == request.status:
            channel_address = await self.__join_channel(request.index, request.channel)

            if channel_address:
                user.channel = request.channel

                return client_to_agent_pb2.CommandReply(
                    status=client_to_agent_pb2.CommandReply.Status.SUCCESS,
                    address=channel_address)
            else:
                return client_to_agent_pb2.CommandReply(
                    status=client_to_agent_pb2.CommandReply.Status.FAILURE)
        elif status.LEAVE_CHANNEL == request.status:
            await self.__remove_user_from_channel(request.index, user.channel)
            self.__users[request.index].channel = 0

            return client_to_agent_pb2.CommandReply(
                status=client_to_agent_pb2.CommandReply.Status.SUCCESS)
        elif status.LIST_USERS == request.status:
            users = await self.__get_users(request.channel)
            channels = tuple(self.__users[index].channel for index in users)

            return client_to_agent_pb2.CommandReply(
                status=client_to_agent_pb2.CommandReply.Status.SUCCESS,
                users=users,
                channels=channels)
        else:
            assert False

    async def run(self) -> None:
        await self.__server.start()
        logging.info('Starting Lobby on %s', self.__address)

        while True:
            try:
                await self.__server.wait_for_termination(timeout=1)
            except KeyboardInterrupt:
                await self.__server.stop(0)

    async def TryUserExit(
            self, request: client_to_agent_pb2.UserRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Empty:
        user = self.__users.get(request.index)

        if user is not None:
            if user.is_invalidated():
                response = client_to_agent_pb2.StatusReply(
                    index=user.index,
                    status=client_to_agent_pb2.StatusReply.Status.QUIT)

                user.statuses.append(response)
                return response

        return client_to_agent_pb2.StatusReply(
            index=user.index,
            status=client_to_agent_pb2.StatusReply.Status.OK)

    async def TryStatusRequest(
            self, request: client_to_agent_pb2.UserRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.StatusReply:
        statuses = self.__get_user(request.index).statuses

        while True:
            if statuses:
                for status in statuses:
                    yield status

                statuses.clear()

            await asyncio.sleep(5)

    async def __remove_user_from_channel(self, user_index: int, port: int) -> None:
        if port not in self.__channels:
            return

        channel = self.__channels[port]
        channel.remove_user(user_index)

        if channel.is_empty():
            del self.__channels[port]
            await channel.stop()
            del channel

            self.__channel_ports.insert(0, port)

    async def __join_channel(self, index: int, channel: collections.Hashable) -> str:
        if channel in self.__channels:
            return self.__channels[channel].address
        else:
            return ''

    async def __get_users(self, channel: collections.Hashable) -> 'tuple[int]':
        if channel in self.__channels:
            return tuple(self.__channels[channel].users)
        else:
            return tuple(self.__users)

    def __get_user(self, index: collections.Hashable) -> User:
        if index in self.__users:
            return self.__users[index]
        else:
            self.__users[index] = user = User(index)
            user.validate()
            return user