from mcdreforged.api.all import PluginServerInterface, Literal, CommandSource, GreedyText
import os
import json
import asyncio
import websockets
import threading
from typing import Dict, Any
from mc_uuid import onlineUUID, offlineUUID

connected_clients = set()
server_instance = None
websocket_server = None
websocket_server_task = None
loop = None
config = {}

def get_config_path():
    return os.path.join(server_instance.get_data_folder(), 'config', 'sealdice.json')

def create_default_config():
    config_path = get_config_path()
    default_config = {
        "_comment1": "这个文件是用于配置SealDice插件的",
        "_comment2": "下面这一项是配置监听地址的，除非你知道你在干什么，否则不要修改",
        "host": "0.0.0.0",
        "_comment3": "下面这一项是配置监听端口的",
        "port": 8887,
        "_comment4": "下面这一项是配置消息名字前缀的",
        "prefix": "§d骰娘§e",
        "_comment5": "下面这一项是配置消息名字的",
        "botname": "§e骰娘§r",
        "_comment6": "下面这一项是配置消息颜色的",
        "replycolor": "§b",
        "_comment7": "颜色代码请自行参照wiki：",
        "_comment8": "https://minecraft.fandom.com/zh/wiki/%E6%A0%BC%E5%BC%8F%E5%8C%96%E4%BB%A3%E7%A0%81?variant=zh"
    }

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=4)
        server_instance.logger.info(f'Default configuration file created at {config_path}')

def load_config():
    global config
    config_path = get_config_path()
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        server_instance.logger.info(f'Configuration loaded from {config_path}')
    else:
        create_default_config()
        load_config()

def start_websocket_server():
    global websocket_server, websocket_server_task, loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    websocket_server = websockets.serve(handle_client, config["host"], config["port"])
    websocket_server_task = loop.run_until_complete(websocket_server)
    try:
        loop.run_forever()
    finally:
        loop.close()

async def handle_client(websocket, path):
    server_instance.logger.info(f'Sealdice connected: {websocket.remote_address}')
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                content = data.get('content', '')
                if content:
                    formatted_message = f'{config["prefix"]}{config["botname"]}: {config["replycolor"]}{content}§r'
                    server_instance.broadcast(formatted_message)
            except json.JSONDecodeError:
                server_instance.logger.warning('Received invalid JSON message from Sealdice')
    except websockets.exceptions.ConnectionClosed:
        server_instance.logger.info(f'Sealdice disconnected: {websocket.remote_address}')
    finally:
        connected_clients.remove(websocket)

def send_to_sealdice(message):
    if not connected_clients:
        server_instance.logger.warning('No connected Sealdice clients to send message')
        return
    data = json.dumps(message)
    asyncio.run(send_message_to_clients(data))

async def send_message_to_clients(message):
    tasks = [client.send(message) for client in connected_clients if client.open]
    if tasks:
        await asyncio.gather(*tasks)

def on_load(server: PluginServerInterface, old_module):
    global server_instance
    server_instance = server
    create_default_config()
    load_config()
    server.register_help_message('!!sealdice', 'Send a message to SealDice')
    server.register_command(
        Literal('!!sealdice')
        .runs(lambda src: src.reply('用法: !!sealdice <内容>'))
        .then(GreedyText('content').runs(on_sealdice_command))
    )
    threading.Thread(target=start_websocket_server, daemon=True).start()
    server.logger.info(f'WebSocket server started at ws://{config["host"]}:{config["port"]}')

def on_sealdice_command(source: CommandSource, context: Dict[str, Any]):
    content = context['content']
    uuid = get_player_uuid(source)
    message = {
        'type': 'message',
        'event': {
            'content': content,
            'isAdmin': source.has_permission(3),
            'name': source.player if source.is_player else 'Console',
            'uuid': uuid if uuid else '',
            'messageType': 'private' if source.is_player else 'group'
        }
    }
    send_to_sealdice(message)

def get_player_uuid(source: CommandSource) -> str:
    player_name = source.player if source.is_player else None
    if player_name:
        try:
            return str(onlineUUID(player_name))
        except:
            return str(offlineUUID(player_name))
    return None

def on_unload(server: PluginServerInterface):
    global websocket_server_task, loop
    if websocket_server_task:
        server.logger.info('Closing WebSocket server...')
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.call_soon_threadsafe(loop.stop)
        websocket_server_task.close()
        loop.run_until_complete(websocket_server_task.wait_closed())
        server.logger.info('WebSocket server closed')
    server.logger.info('SealDice MCDReforged Plugin unloaded')
