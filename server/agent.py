import collections
import logging
import socket
import time

import grpc

from proto import client_to_agent_pb2
from proto import client_to_agent_pb2_grpc


User = collections.namedtuple(
    'User', ('IP', 'Index', 'TimeStamp')
)
RemoteProcedureCall = collections.namedtuple(
    'RemoteProcedureCall', ('Channel', 'Stub')
)


class Agent(client_to_agent_pb2_grpc.Agent):
    __index = 0
    __heartbeat_rpc = None
    __lobby_rpc = None

    def __init__(self, agent_address: str, heartbeat_address: str, lobby_address: str):
        self.__users = []
        self.__address = agent_address
        self.__heartbeat_address = heartbeat_address
        self.__lobby_address = lobby_address
        self.__server = self.__create_server(agent_address)

    async def TryLogin(
            self, request: client_to_agent_pb2.LoginRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.LoginReply:
        self.__index += 1

        self.__add_user(request.ip, self.__index)

        return client_to_agent_pb2.LoginReply(
            index=self.__index, heartbeat_ip=self.__heartbeat_address, lobby_ip=self.__lobby_address)

    async def run(self) -> None:
        await self.__server.start()
        logging.info('Starting Agent on %s', self.__address)

        while True:
            try:
                await self.__server.wait_for_termination(timeout=1)
            except KeyboardInterrupt:
                await self.__server.stop(0)

            await self.__check_user()

    def __create_server(self, address: str) -> grpc.aio.server:
        server = grpc.aio.server()
        server.add_insecure_port(address)

        client_to_agent_pb2_grpc.add_AgentServicer_to_server(self, server)

        return server

    def __add_user(self, ip: str, index: int) -> None:
        assert ip not in self.__users

        time_stamp = self.__get_next_time_stamp()
        self.__users.append(User(ip, index, time_stamp))

        logging.debug(f'User connected {ip} {index}')

        if self.__heartbeat_rpc is None:
            assert self.__lobby_rpc is None

            self.__heartbeat_rpc = self.__create_heartbeat_rpc()
            self.__lobby_rpc = self.__create_lobby_rpc()
        else:
            assert isinstance(self.__heartbeat_rpc, RemoteProcedureCall)
            assert isinstance(self.__lobby_rpc, RemoteProcedureCall)

    async def __check_user(self) -> None:
        if not self.__users:
            return

        user = self.__users.pop(0)

        if user.TimeStamp > self.__get_time_stamp():
            self.__users.append(user)
            return

        request = client_to_agent_pb2.UserRequest(index=user.Index)
        response = await self.__heartbeat_rpc.Stub.TryUserLives(request)

        if response.Status.LIVE == response.status:
            logging.debug(f'User lives: {user.IP}, {user.Index}')

            response = await self.__lobby_rpc.Stub.TryUserExit(request)

            if client_to_agent_pb2.StatusReply.Status.OK == response.status:
                self.__users.append(User(user.IP, user.Index, self.__get_next_time_stamp()))
            else:
                assert client_to_agent_pb2.StatusReply.Status.QUIT == response.status
        else:
            assert response.Status.UNKNOWN == response.status

            await self.__lobby_rpc.Stub.TryUserRemove(request)

            logging.debug(f'User removed: {user.IP}, {user.Index}')

    def __create_heartbeat_rpc(self) -> RemoteProcedureCall:
        channel = grpc.aio.insecure_channel(self.__heartbeat_address)
        stub = client_to_agent_pb2_grpc.HeartbeatStub(channel)

        return RemoteProcedureCall(channel, stub)

    def __create_lobby_rpc(self) -> RemoteProcedureCall:
        channel = grpc.aio.insecure_channel(self.__lobby_address)
        stub = client_to_agent_pb2_grpc.LobbyStub(channel)

        return RemoteProcedureCall(channel, stub)

    @staticmethod
    def __get_time_stamp() -> int:
        return int(time.time())

    @classmethod
    def __get_next_time_stamp(cls) -> int:
        return cls.__get_time_stamp() + 30
