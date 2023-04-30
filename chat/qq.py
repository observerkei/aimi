import abc
from typing import List, Tuple, Union, Set, Any

from tool.config import config

class ChatQQ:
    response_user_ids: Set[int] = {}
    response_group_ids: Set[int] = {}
    master_id: int = 0
    
    class MessageType:
        Private = 'private'
        Group = 'group'

    class QQMessageBase(abc.ABC):
        post_type: str
        message_type: str
        time: int
        self_id: int
        sub_type: str
        font: int
        message_id: int
        user_id: int
        message: str
        raw_message: str

    class PrivateMessage(QQMessageBase, abc.ABC):
        class PrivateSender(abc.ABC):
            age: int
            nickname: str
            sex: str
            user_id: int
        sender: PrivateSender
        target_id: int

    class GroupMessage(QQMessageBase, abc.ABC):
        class GroupSender(abc.ABC):
            age: int
            area: str
            card: str
            level: str
            nickname: str
            role: str
            sex: str
            title: str
            user_id: int
        group_id: int
        message_seq: int
        anonymous: Any
        sender: GroupSender
    
    class CqType:
        At = 'at'
        Image = 'image'
        Face = 'face'
    
    class Cq(abc.ABC):
        pass
    
    class CqAt(Cq, abc.ABC):
        qq: int
    
    class CqImage(Cq, abc.ABC):
        file: str
        url: str
    
    class CqFace(Cq, abc.ABC):
        id: int
    
    # 发送 私聊消息
    def get_send_private_request(go_host: str, go_port: int, user_id: int, message: str) -> str:
        get_request = "http://{}:{}/send_private_msg?user_id={}&message={}".format(
            go_host, go_port, user_id, message)
        return get_request
    
    # 发送 群聊消息
    def get_send_group_request(go_host: str, go_port: int, group_id: int, message: str) -> str:
        get_request = "http://{}:{}/send_group_msg?group_id={}&message={}".format(
                go_host, go_port, group_id, message)
        return get_request
  
    def need_reply(self, user: dict):
        if user['chat'] != 'qq':
            return False
        if user['user_id'] and user['user_id'] == self.master_id:
            return True
        if user['group_id'] and not (user['group_id'] in self.response_group_ids):
            return False
        if user['user_id'] and user['user_id'] in self.response_user_ids:
            return True
    
        return False
    
    # 如果有人@我了，我才回复
    def someone_at_me(self, parsed_cq_codes: List[Tuple[object, str]]) -> bool:
        for p_cq_code, cq_type in parsed_cq_codes:
            if cq_type == CqType.At:
                cq_at: CqAt = p_cq_code
                if cq_at.qq == self.user_id:
                    return True
        return False

    def __init__(self):
        self.__load_setting()

    def __load_setting(self):
        try:
            self.master_id = config.setting['qq']['master_id']
        except:
            self.master_id = 0

        try:
            self.response_user_ids = set(config.setting['qq']['response_user_ids'])
        except:
            self.response_user_ids = set()        
        try:
            self.response_group_ids = set(config.setting['qq']['response_group_ids'])
        except:
            self.response_group_ids = set()


chat_qq = ChatQQ()
