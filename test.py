import asyncio

import grpc
import mock
import pytest

from proto.client_to_agent_pb2 import *
from server.agent import Agent
from server.heartbeat import Heartbeat
import server.channel as channel
import server.lobby as lobby


LOBBY_IP = 'localhost:50052'
HEARTBEAT_IP = 'localhost:50051'


@pytest.mark.asyncio
async def test_agent() -> None:
    agent_ip = 'localhost:50050'
    service = Agent(agent_ip, HEARTBEAT_IP, LOBBY_IP)

    message = LoginRequest()
    mock_context = mock.create_autospec(spec=grpc.aio.ServicerContext)
    response = await service.TryLogin(message, mock_context)
    assert response.index == 1


@pytest.mark.asyncio
async def test_lobby() -> None:
    channel_port = 50053
    service = lobby.Lobby(LOBBY_IP, 'localhost', (channel_port,))
    user_index = 0
    test_message = 'Hello, world'
    message = Chat(index=user_index)

    mock_context = mock.create_autospec(spec=grpc.aio.ServicerContext)
    service._Lobby__users[user_index] = user = lobby.User(user_index)
    user.chats.append(Chat(index=1, text=test_message))

    response_iterator = service.TryChatReceive(message, mock_context)
    response = await response_iterator.__anext__()
    assert response.text == test_message

    message = Chat(index=2, text=test_message)
    await service.TryChatSend(message, mock_context)

    response = await response_iterator.__anext__()
    assert response.text == test_message

    await service.TryCommand(
        CommandRequest(index=user_index, status=CommandRequest.Status.MAKE_CHANNEL),
        mock_context)
    assert service._Lobby__channels
    assert user.channel == channel_port

    response = await service.TryCommand(
        CommandRequest(index=user_index, status=CommandRequest.Status.LIST_CHANNELS),
        mock_context)
    assert response.channels

    response = await service.TryCommand(
        CommandRequest(index=user_index, status=CommandRequest.Status.LIST_USERS),
        mock_context)
    assert response.users and response.channels

    await service.TryCommand(
        CommandRequest(index=user_index, status=CommandRequest.Status.LEAVE_CHANNEL),
        mock_context)
    assert not service._Lobby__channels
    assert not user.channel


@pytest.mark.asyncio
async def test_channel() -> None:
    user0_index = 0
    user1_index = 1
    test_message = 'Hello, world'

    ch = channel.Channel('localhost', 50053)
    handler = ch._Channel__handler
    mock_context = mock.create_autospec(spec=grpc.aio.ServicerContext)
    iterator = handler.TryChatReceive(Chat(index=user0_index), mock_context)
    handler._Handler__users[user0_index] = user = channel.User()
    user.chats.append(Chat(index=user1_index, text=test_message))

    response = await iterator.__anext__()
    assert response.index == user1_index
    assert response.text == test_message


@pytest.mark.asyncio
async def test_heartbeat() -> None:
    user_index = 0
    mock_context = mock.create_autospec(spec=grpc.aio.ServicerContext)
    heartbeat = Heartbeat(HEARTBEAT_IP)

    iterator = heartbeat.TryHeartbeat(HeartbeatRequest(index=user_index), mock_context)
    response = await iterator.__anext__()
    assert response.time

    response = await heartbeat.TryUserLives(UserRequest(index=user_index), mock_context)
    assert response.status == UserLivesReply.Status.LIVE

    users = heartbeat._Heartbeat__users
    users[user_index] = heartbeat._Heartbeat__get_time_stamp() - 1
    response = await heartbeat.TryUserLives(UserRequest(index=user_index), mock_context)
    assert response.status == UserLivesReply.Status.UNKNOWN
    assert not users

