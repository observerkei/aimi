import hashlib
import copy
from typing import Any, Dict

from tool.util import log_dbg, log_info, log_err
from core.aimi_plugin import ChatBot
from aimi_plugin.bot.type import BotType as ChatBotType
from core.task import Task


class Session:
    chatbots: Dict[str, ChatBot] = {}
    __setting: Dict = {}

    def __init__(self, setting):
        self.__setting = setting
    
    @property
    def setting(self):
        return self.__setting

    def dup_setting(self, api_key: str):
        setting = copy.deepcopy(self.__setting)
        if ChatBotType.OpenAI in setting and 'api_key' in setting[ChatBotType.OpenAI]:
            setting[ChatBotType.OpenAI]['api_key'] = api_key
        return setting

    def create_session_id(self, key: str):
        return hashlib.sha256(key.encode()).hexdigest()

    def has_session(self, session_id: str) -> bool:
        return session_id in self.chatbots

    def __create_chabot(self, setting: Dict) -> ChatBot:
        chatbot = ChatBot(setting)
        task_setting = setting['task'] if 'task' in setting else {}
        task = Task(
            chatbot=chatbot, 
            setting=task_setting)
        chatbot.append(ChatBotType.Task, task)
        return chatbot

    # 整个 chatbot 结构更新才能用这个, 会主动释放原来的 chatbot (调用exit保存信息)
    def __update_session(self, session_id: str, chatbot: ChatBot) -> str:
        if session_id not in self.chatbots or not chatbot:
            return None

        try:
            old_chatbot = None
            if session_id in self.chatbots:
                old_chatbot = self.chatbots[session_id]
            
            self.chatbots[session_id] = chatbot

            try:
                if old_chatbot:
                    log_dbg(f"release old session chatbot: {session_id}")
                    old_chatbot.when_exit()
            except Exception as e:
                log_err(f"fail to release old session: {session_id}: {str(e)}")

            log_info(f"new session: {session_id}")

            return session_id
        
        except Exception as e:
            log_err(f"fail to create new session: {key} :{str(e)}")
            return None
    
    def new_session(self, key: str, setting: Dict) -> str:
        session_id = self.create_session_id(key)
        if self.has_session(session_id):
            log_err(f"already have session_id: {session_id}")
            return None 

        try:
            self.chatbots[session_id] = self.__create_chabot(setting)
            return session_id
        except Exception as e:
            log_err(f"fail to new session: {e}")
            return None

    def update_session_by_api_key(self, session_id: str, api_key: str) -> bool:
        if not self.has_session(session_id):
            return False
        
        chatbot = self.chatbots[session_id]

        bot_setting = chatbot.get_bot_setting(ChatBotType.OpenAI)
        bot_setting['api_key'] = api_key

        bot = chatbot.reload_bot(ChatBotType.OpenAI, bot_setting)
        if not bot:
            log_err(f"fail to reload bot: {session_id}")
            return False

        return True

    def get_chatbot(self, session_id: str) -> ChatBot:
        if not self.has_session(session_id):
            log_dbg(f"no has session_id: {session_id}")
            return None

        return self.chatbots[session_id]

    def get_chatbot_setting_api_key(self, session_id: str) -> str:
        if session_id not in self.chatbots:
            return ""
        chatbot = self.get_chatbot(session_id)

        api_key = ""
        try:
            api_key = chatbot.setting[ChatBotType.OpenAI]["api_key"]
        except Exception as e:
            log_err(f"fail to get api_key, session_id({session_id})")
            api_key = ""
        return api_key

    def when_exit(self):
        for session_id, chatbot in self.chatbots.items():
            try:
                chatbot.when_exit()
            except Exception as e:
                log_err(f"fail to exit {session_id} chatbot: {e}")
    