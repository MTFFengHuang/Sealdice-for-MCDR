from mcdreforged.api.all import PluginServerInterface, Literal, CommandSource, GreedyText
from websocket_server import WebsocketServer
import threading
import os
import json
from typing import Dict, Any
from mc_uuid import onlineUUID, offlineUUID

connected_clients = []
server_instance = None
websocket_server = None
config = {}


def get_config_path():
    return os.path.join(server_instance.get_data_folder(), 'sealdice.json')


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
        "_comment7": "下面这一项是开关是否监听所有聊天",
        "_comment8": "为 true 时监听所有聊天信息并发送到 SealDice，为 false 时关闭监听",
        "enable_chat_listener": True
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
    global websocket_server
    websocket_server = WebsocketServer(host=config["host"], port=config["port"])
    websocket_server.set_fn_new_client(on_client_connect)
    websocket_server.set_fn_client_left(on_client_disconnect)
    websocket_server.set_fn_message_received(on_message_received)
    websocket_server.run_forever()


def on_client_connect(client, server):
    connected_clients.append(client)
    server_instance.logger.info(f"Client connected: {client['address']}")


def on_client_disconnect(client, server):
    connected_clients.remove(client)
    server_instance.logger.info(f"Client disconnected: {client['address']}")


def on_message_received(client, server, message):
    server_instance.logger.info(f"Message received: {message}")
    try:
        data = json.loads(message)
        content = data.get('content', '')
        if content:
            formatted_message = f'{config["prefix"]}{config["botname"]}: {config["replycolor"]}{content}§r'
            server_instance.broadcast(formatted_message)
    except json.JSONDecodeError:
        server_instance.logger.warning(f"Invalid JSON received from client: {client['address']}")


def send_to_sealdice(message: Dict[str, Any]):
    if not connected_clients:
        server_instance.logger.warning('No connected Sealdice clients to send message')
        return
    data = json.dumps(message)
    for client in connected_clients:
        websocket_server.send_message(client, data)


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

    if config.get("enable_chat_listener", True):
        server.logger.info("Chat listener is enabled. Listening to all chat messages.")
        server.register_event_listener('mcdr.user_info', on_chat_message)
    else:
        server.logger.info("Chat listener is disabled.")

    threading.Thread(target=start_websocket_server, daemon=True).start()
    server.logger.info(f"WebSocket server started at ws://{config['host']}:{config['port']}")


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
            'messageType': 'private' if source.is_player else 'group',
        }
    }
    send_to_sealdice(message)


def on_chat_message(server: PluginServerInterface, info: Any):
    if info.is_player:
        player_name = info.player
        uuid = get_player_uuid(info)
        permission_level = server.get_permission_level(player_name)  # 获取玩家权限等级
        message = {
            'type': 'message',
            'event': {
                'content': info.content,
                'isAdmin': permission_level >= 3,  # 判断是否是管理员
                'name': player_name,
                'uuid': uuid,
                'messageType': 'group',
            }
        }
        send_to_sealdice(message)


def get_player_uuid(info: Any) -> str:
    player_name = info.player if info.is_player else None
    if player_name:
        try:
            return str(onlineUUID(player_name))
        except:
            return str(offlineUUID(player_name))
    return None


def on_unload(server: PluginServerInterface):
    global websocket_server
    if websocket_server:
        server.logger.info('Closing WebSocket server...')
        websocket_server.shutdown_gracefully()
        server.logger.info('WebSocket server closed')
    server.logger.info('SealDice MCDReforged Plugin unloaded')
