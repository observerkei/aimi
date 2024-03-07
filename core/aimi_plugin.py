import os
import importlib.util
from typing import Any, List, Generator, Dict

from tool.util import log_info, log_err, log_dbg, load_module
from tool.config import Config
from aimi_plugin.bot_example import Bot


# call bot_ plugin example
class Bot:
    # This has to be globally unique
    type: str = "public_name"
    trigger: str = "#public_name"
    bot: Any

    def __init__(self):
        self.bot = None

    @property
    def init(self) -> bool:
        return self.bot.init

    # when time call bot
    def is_call(self, caller: Any, req) -> bool:
        question = caller.bot_get_question(req)
        if trigger in question:
            return True
        return False

    # get support model
    def get_models(self, caller: Any) -> List[str]:
        return [self.type]

    # ask bot
    def ask(self, caller: Any, ask_data) -> Generator[dict, None, None]:
        question = caller.bot_get_question(ask_data)
        yield caller.bot_set_response(code=1, message="o")
        yield caller.bot_set_response(code=0, message="ok.")
        # if error, then: yield caller.bot_set_response(code=-1, message="err")

    # exit bot
    def when_exit(self, caller: Any):
        pass

    # init bot
    def when_init(self, caller: Any):
        pass

    # no need define plugin_prefix
    plugin_prefix = "bot_"

    # pack ask_data
    def bot_pack_ask_data(
        self,
        question: str,
        model: str = "",
        messages: List = [],
        conversation_id: str = "",
    ):
        return {
            "question": question,
            "model": model,
            "messages": messages,
            "conversation_id": conversation_id,
        }

    # no need define bot_get_question
    def bot_get_question(self, ask_data):
        if "question" in ask_data:
            return ask_data["question"]
        return ""

    # no need define bot_get_model
    def bot_get_model(self, ask_data):
        if "model" in ask_data:
            return ask_data["model"]
        return ""

    # no need define bot_get_messages
    def bot_get_messages(self, ask_data):
        if "messages" in ask_data:
            return ask_data["messages"]
        return ""

    def bot_get_conversation_id(self, ask_data):
        if "conversation_id" in ask_data:
            return ask_data["conversation_id"]
        return ""

    def bot_get_timeout(self, ask_data):
        if "timeout" in ask_data:
            return ask_data["timeout"]
        return ""

    # no need define bot_set_response
    def bot_set_response(self, code: int, message: str) -> Any:
        return {"code": code, "message": message}

    def bot_load_setting(self, type: str):
        return Config.load_setting(type)

    def bot_log_dbg(self, msg: str):
        return log_dbg(msg, is_plugin=True)

    def bot_log_err(self, msg: str):
        return log_err(msg, is_plugin=True)

    def bot_log_info(self, msg: str):
        return log_info(msg, is_plugin=True)


class ChatBotType:
    Bing: str = "bing"
    Google: str = "google"
    OpenAI: str = "openai"
    Wolfram: str = "wolfram"
    ChimeraGPT: str = "wolfram"


class ChatBot:
    bots: Dict[str, Bot] = {}
    bot_caller: Bot = Bot()

    def __init__(self):
        pass

    def append(self, type: str, bot: Bot):
        if type:
            self.bots[type] = bot

    def pack_ask_data(
        self,
        question: str,
        model: str = "",
        messages: List = [],
        conversation_id: str = "",
    ):
        return self.bot_caller.bot_pack_ask_data(
            question=question,
            model=model,
            messages=messages,
            conversation_id=conversation_id,
        )

    def ask(self, type: str, ask_data: dict = {}) -> Generator[dict, None, None]:
        if self.has_type(type):
            try:
                yield from self.bots[type].ask(self.bot_caller, ask_data)
            except Exception as e:
                log_err(f"fail to ask bot: {e}: {type}: {ask_data}")
        else:
            log_err(f"no model to ask of type: {type}")

    def get_bot(self, type: str) -> Bot:
        if self.has_type(type):
            return self.bots[type]
        return None

    def has_type(self, type: str) -> bool:
        if type in self.bots:
            return True
        return None

    def has_bot_init(self, type: str) -> bool:
        if not self.has_type(type):
            return False
        return self.bots[type].init

    def get_bot_models(self, type: str) -> List[str]:
        if not self.has_bot_init(type):
            return []
        return self.bots[type].get_models(self.bot_caller)

    def each_bot(self) -> Generator[tuple[str, Bot], None, None]:
        for bot_type, bot in self.bots.items():
            yield bot_type, bot


class AimiPlugin:
    bots: Dict[str, Bot] = {}
    bots_type: List[str] = []
    bot_obj: Bot = Bot()
    plugin_path = "./aimi_plugin"

    def __init__(self):
        self.__load_setting()

        self.__load_bot()

        self.when_init()

    def __load_setting(self):
        try:
            setting = Config.load_setting("aimi")
        except Exception as e:
            log_err(f"fail to load {self.type}: {e}")
            setting = {}
            return

        try:
            self.plugin_path = setting["plugin_path"]
        except Exception as e:
            log_err(f"fail to get plugin_path: {e}")
            self.plugin_path = "./aimi_plugin"

    def __load_bot(self):
        # 遍历目录中的文件
        for filename, module in load_module(
            module_path=self.plugin_path, load_name=["Bot"], file_start="bot_"
        ):
            # skip example
            if self.bot_obj.plugin_prefix + "example.py" == filename:
                continue

            try:
                bot = module.Bot()
                bot_type = bot.type
                if bot_type in self.bots:
                    raise Exception(f"{bot_type} has in bots")
                self.bots[bot_type] = bot
                log_info(f"add plugin bot_type:{bot_type}  from: {filename}")
            except Exception as e:
                log_err(f"fail to add plugin bot: {e} file: {filename}")

    def bot_has_type(self, type) -> bool:
        if not len(self.bots):
            return False

        for bot_type, bot in self.bots.items():
            try:
                if bot_type == type:
                    return True
            except Exception as e:
                log_err(f"fail to check type bot: {bot_type} err: {e}")

        return False

    def when_exit(self):
        if not len(self.bots):
            return

        for bot_type, bot in self.bots.items():
            try:
                bot.when_exit(self.bot_obj)
            except Exception as e:
                log_err(f"fail to exit bot: {bot_type} err: {e}")

    def when_init(self):
        if not len(self.bots):
            return

        for bot_type, bot in self.bots.items():
            try:
                bot.when_init(self.bot_obj)
            except Exception as e:
                log_err(f"fail to init bot: {bot_type} err: {e}")

    def each_bot(self) -> Generator[tuple[str, Bot], None, None]:
        for bot_type, bot in self.bots.items():
            yield bot_type, bot
