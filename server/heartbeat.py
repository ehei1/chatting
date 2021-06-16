import asyncio
import logging
import socket
import time

import grpc

from proto import client_to_agent_pb2
from proto import client_to_agent_pb2_grpc


class Heartbeat(client_to_agent_pb2_grpc.Heartbeat):
    __server = None
    __handler = None
    __address = ''
    __users = None
    __any_messages = None
    __live_seconds = 5

    def __init__(self, address: str):
        self.__users = {}
        self.__address = address
        self.__server = server = grpc.aio.server()

        client_to_agent_pb2_grpc.add_HeartbeatServicer_to_server(self, server)

        server.add_insecure_port(address)

    async def TryHeartbeat(
            self, request: client_to_agent_pb2.HeartbeatRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.HeartbeatReply:
        assert request.index not in self.__users

        while True:
            time_stamp = self.__get_time_stamp()
            self.__users[request.index] = time_stamp + self.__live_seconds

            yield client_to_agent_pb2.HeartbeatReply(time=time_stamp)

            await asyncio.sleep(self.__live_seconds)

    async def TryUserLives(
            self, request: client_to_agent_pb2.UserRequest,
            context: grpc.aio.ServicerContext) -> client_to_agent_pb2.UserLivesReply:
        if request.index not in self.__users:
            return client_to_agent_pb2.UserLivesReply(status=client_to_agent_pb2.UserLivesReply.Status.UNKNOWN)

        time_stamp = self.__users[request.index]

        if self.__get_time_stamp() > time_stamp:
            status = client_to_agent_pb2.UserLivesReply.Status.UNKNOWN

            del self.__users[request.index]
        else:
            status = client_to_agent_pb2.UserLivesReply.Status.LIVE

        return client_to_agent_pb2.UserLivesReply(status=status)

    async def run(self) -> None:
        await self.__server.start()
        logging.info('Starting Heartbeat on %s', self.__address)

        try:
            await self.__server.wait_for_termination()
        except KeyboardInterrupt:
            await self.__server.stop(0)

    @staticmethod
    def __get_time_stamp() -> int:
        return int(time.time())