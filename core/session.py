import hashlib
import copy
from typing import Any, Dict

from tool.util import log_dbg, log_info, log_err
from core.aimi_plugin import ChatBot
from aimi_plugin.bot.type import BotType as ChatBotType
from core.task import Task
from pydantic import BaseModel, constr


class SessionData(BaseModel):
    chatbot: Any
    previous_api_type: str


class Session:
    __setting: Dict = {}
    __data: Dict[str, SessionData] = {}

    def __init__(self, setting):
        self.__setting = setting

    @property
    def setting(self):
        return self.__setting

    def dup_setting(self, api_key: str):
        setting = copy.deepcopy(self.__setting)
        if ChatBotType.OpenAI in setting and "api_key" in setting[ChatBotType.OpenAI]:
            setting[ChatBotType.OpenAI]["api_key"] = api_key
        return setting

    def create_session_id(self, key: str):
        return hashlib.sha256(key.encode()).hexdigest()

    def has_session(self, session_id: str) -> bool:
        return session_id in self.__data

    def __create_chabot(self, setting: Dict) -> ChatBot:
        chatbot = ChatBot(setting)
        task_setting = setting["task"] if "task" in setting else {}
        task = Task(chatbot=chatbot, setting=task_setting)
        chatbot.append(ChatBotType.Task, task)
        return chatbot

    def new_session(self, key: str, setting: Dict) -> str:
        session_id = self.create_session_id(key)
        if self.has_session(session_id):
            log_err(f"already have session_id: {session_id}")
            return session_id

        try:
            chatbot = self.__create_chabot(setting)
            previous_api_type = ""
            self.__data[session_id] = SessionData(
                chatbot=chatbot, previous_api_type=previous_api_type
            )
            log_info(f"create session_id: {session_id}")
            return session_id
        except Exception as e:
            log_err(f"fail to new session: {e}")
            return None

    def update_session_by_api_key(self, session_id: str, api_key: str) -> bool:
        if not self.has_session(session_id):
            return False

        chatbot: ChatBot = self.__data[session_id].chatbot

        bot_setting = chatbot.get_bot_setting(ChatBotType.OpenAI)
        bot_setting["api_key"] = api_key

        bot = chatbot.reload_bot(ChatBotType.OpenAI, bot_setting)
        if not bot:
            log_err(f"fail to reload bot: {session_id}")
            return False

        return True

    def get_previous_api_type(self, session_id: str) -> str:
        if not self.has_session(session_id):
            log_dbg(f"no has session_id: {session_id}")
            return None
        return self.__data[session_id].previous_api_type

    def set_previous_api_type(self, session_id: str, api_type: str) -> str:
        if not self.has_session(session_id):
            log_dbg(f"no has session_id: {session_id}")
            return None

        self.__data[session_id].previous_api_type = api_type

    def get_chatbot(self, session_id: str) -> ChatBot:
        if not self.has_session(session_id):
            log_dbg(f"no has session_id: {session_id}")
            return None

        return self.__data[session_id].chatbot

    def get_chatbot_setting_api_key(self, session_id: str) -> str:
        if not self.has_session(session_id):
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
        for session_id, session_data in self.__data.items():
            try:
                chatbot: ChatBot = session_data.chatbot
                chatbot.when_exit()
            except Exception as e:
                log_err(f"fail to exit {session_id} chatbot: {e}")
