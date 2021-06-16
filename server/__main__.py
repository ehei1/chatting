import argparse
import asyncio
import asyncio.runners
import logging
import threading

from server.agent import Agent
from server.heartbeat import Heartbeat
from server.lobby import Lobby


async def launch_sync(service_type, *arguments, **keywords) -> None:
    service = service_type(*arguments, **keywords)
    await service.run()


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser(prog='python -m server', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--agent', dest='agent', help='agent address', type=str, default='localhost:50050')
    parser.add_argument('--heartbeat', dest='heartbeat', help='heartbeat address', type=str, default='localhost:50051')
    parser.add_argument('--lobby', dest='lobby', help='lobby address', type=str, default='localhost:50052')
    parser.add_argument('--channel', dest='channel', help='channel ip', type=str, default='localhost')
    parser.add_argument(
        '--ports', dest='ports', help='available ports for channel', nargs='*', type=int,
        default=(50054, 50055, 50056, 50057))

    arguments = parser.parse_args()

    agent = Agent(arguments.agent, arguments.heartbeat, arguments.lobby)
    heartbeat = Heartbeat(arguments.heartbeat)
    lobby = Lobby(arguments.lobby, arguments.channel, arguments.ports)

    servers = asyncio.gather(
        *(agent.run(), heartbeat.run(), lobby.run()))
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(servers)

    loop.close()


if __name__ == '__main__':
    main()