import hashlib
from typing import Any, Dict

from tool.util import log_dbg, log_info, log_err
from core.aimi_plugin import ChatBot
from aimi_plugin.bot.type import BotType as ChatBotType
from core.task import Task


class Session:
    chatbots: Dict[str, ChatBot] = {}

    def __init__(self):
        pass

    def create_session_id(self, key: str):
        return hashlib.sha256(key.encode()).hexdigest()

    def has_session(self, session_id: str) -> bool:
        return session_id in self.chatbots

    def new_session(self, key: str, setting: Dict):
        try:
            chatbot = ChatBot(setting)
            task_setting = setting['task'] if 'task' in setting else {}
            task = Task(
                chatbot=chatbot, 
                setting=task_setting)
            chatbot.append(ChatBotType.Task, task)
            
            session_id = self.create_session_id(key)

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

    def get_chatbot(self, session_id: str):
        if not self.has_session(session_id):
            log_dbg(f"no has session_id: {session_id}")
            return None

        return self.chatbots[session_id]

    def when_exit(self):
        for session_id, chatbot in self.chatbots.items():
            try:
                chatbot.when_exit()
            except Exception as e:
                log_err(f"fail to exit {session_id} chatbot: {e}")
    