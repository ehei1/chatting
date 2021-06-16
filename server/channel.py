import asyncio
import collections
import logging
import weakref

import grpc

from proto import client_to_agent_pb2
from proto import client_to_agent_pb2_grpc


Status = collections.namedtuple('Status', ('Status', 'Index', 'Channel'))


class User:
    def __init__(self):
        self.chats = []
        self.statuses = []


class Handler(client_to_agent_pb2_grpc.Channel):
    def __init__(self, channel_index: int):
        self.__users = collections.defaultdict(User)
        self.__channel_index = channel_index

    async def TryChatSend(
            self, request: client_to_agent_pb2.Chat,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Empty:
        if request.text:
            for index in self.__users.keys() - {request.index}:
                self.__users[index].chats.append(request)

        return client_to_agent_pb2.Empty()

    async def TryChatReceive(
            self, request: client_to_agent_pb2.Chat,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Chat:
        user = self.__users[request.index]
        chats = user.chats

        while True:
            if chats:
                for chat in chats:
                    yield chat

                chats.clear()

            await asyncio.sleep(1)

    async def TryUserRemove(
            self, request: client_to_agent_pb2.UserRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.Empty:
        assert request.index in self.__users

        for user in self.__users.values():
            user.statuses.append(client_to_agent_pb2.StatusReply(
                status=client_to_agent_pb2.StatusReply.Status.LEAVE_USER,
                index=request.index,
                channel=self.__channel_index))

        del self.__users[request.index]

        return client_to_agent_pb2.Empty()

    async def TryStatusRequest(
            self, request: client_to_agent_pb2.UserRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.StatusReply:
        user = self.__users[request.index]
        statuses = user.statuses

        self.__add_status(
            client_to_agent_pb2.StatusReply(
                status=client_to_agent_pb2.StatusReply.Status.JOIN_USER,
                index=request.index,
                channel=self.__channel_index))

        while True:
            if statuses:
                for status in statuses:
                    yield status

                statuses.clear()

            await asyncio.sleep(1)

    def remove_user(self, index: int) -> None:
        self.__users.pop(index, None)

        self.__add_status(
            client_to_agent_pb2.StatusReply(
                status=client_to_agent_pb2.StatusReply.Status.LEAVE_USER,
                index=index,
                channel=self.__channel_index))

    def is_empty(self) -> bool:
        return not self.__users

    @property
    def users(self) -> 'collections.Iterable[int]':
        return self.__users.keys()

    def __add_status(self, response: client_to_agent_pb2.StatusReply) -> None:
        for user in self.__users.values():
            user.statuses.append(response)


class Channel:
    def __init__(self, ip: str, port: int):
        self.__address = address = f'{ip}:{port}'
        self.__server = server = grpc.aio.server()
        server.add_insecure_port(address)

        handler = Handler(port)
        self.__handler = weakref.proxy(handler)
        client_to_agent_pb2_grpc.add_ChannelServicer_to_server(handler, server)

    def __del__(self):
        logging.debug('Closing Channel on %s', self.__address)

    async def run(self) -> None:
        await self.__server.start()
        await self.__server.wait_for_termination(1)

        logging.info('Starting Channel on %s', self.__address)

    async def stop(self) -> None:
        await self.__server.stop(0)

    def remove_user(self, index: int) -> None:
        self.__handler.remove_user(index)

    def is_empty(self) -> bool:
        return self.__handler.is_empty()

    @property
    def address(self) -> str:
        return self.__address

    @property
    def users(self) -> 'collections.Iterable[int]':
        return self.__handler.users
