from typing import Any, List, Generator, Dict, Optional, Union
import shutil

from tool.util import log_info, log_err, log_dbg, load_module
from tool.config import Config
from aimi_plugin.bot.type import Bot as BotBase
from aimi_plugin.bot.type import BotType as ChatBotTypeBase
from aimi_plugin.bot.type import BotAskData as BotAskDataBase
from aimi_plugin.action.type import ActionToolItem as ActionToolItemBase
from pydantic import BaseModel, constr

class ChatBotType(ChatBotTypeBase):
    pass

class BotAskData(BotAskDataBase):
    pass

# call bot_ plugin example
class Bot(BotBase):
    # This has to be globally unique
    type: str = "public_name"
    trigger: str = "#public_name"
    bot: BotBase
    # no need define plugin_prefix
    plugin_prefix = "bot_"
    chatbot: Any 

    def __init__(self):
        self.bot = None

    @property
    def init(self) -> bool:
        return self.bot.init

    # when time call bot
    def is_call(self, caller: BotBase, req) -> bool:
        return False

    # get support model
    def get_models(self, caller: BotBase) -> List[str]:
        return [self.type]

    # ask bot
    def ask(self, caller: BotBase, ask_data: BotAskData) -> Generator[dict, None, None]:
        question = ask_data.question
        yield caller.bot_set_response(code=1, message="o")
        yield caller.bot_set_response(code=0, message="ok.")
        # if error, then: yield caller.bot_set_response(code=-1, message="err")

    def bot_ask(self, caller: BotBase, bot_type: str, ask_data: BotAskData) -> Generator[dict, None, None]:
        if self.chatbot and self.chatbot.bot:
            yield from self.chatbot.bot(self, bot_type, ask_data)

    # exit bot
    def when_exit(self, caller: BotBase):
        pass

    # init bot
    def when_init(self, caller: BotBase):
        pass

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


class ChatBot:
    bots: Dict[str, Bot] = {}
    bot_caller: Bot = Bot()
    bot_path: str = "./aimi_plugin/bot"

    def __init__(self, bot_path):
        self.bot_path = bot_path
        self.bot_caller.chatbot = self
        self.__load_bot()

    def __load_bot(self):
        # 遍历目录中的文件
        for filename, module in load_module(
            module_path=self.bot_path,
            load_name=["Bot"],
            file_start=self.bot_caller.plugin_prefix,
        ):
            # skip example
            if self.bot_caller.plugin_prefix + "example.py" == filename:
                continue

            try:
                bot: Bot = module.Bot()
                bot_type = bot.type
                if self.has_type(bot_type):
                    raise Exception(f"{bot_type} has in bots")

                self.append(bot_type, bot)

                log_info(f"add bot bot_type:{bot_type}  from: {filename}")
            except Exception as e:
                log_err(f"fail to add bot bot: {e} file: {filename}")

    def append(self, type: str, bot: Bot):
        if type:
            self.bots[type] = bot
    
    def ask(self, type: str, ask_data: BotAskData) -> Generator[dict, None, None]:
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

    def when_exit(self):
        if not len(self.bots):
            return

        for bot_type, bot in self.bots.items():
            try:
                bot.when_exit(self.bot_caller)
            except Exception as e:
                log_err(f"fail to exit bot: {bot_type} err: {e}")

    def when_init(self, setting: dict = {}):
        if not len(self.bots):
            return

        for bot_type, bot in self.bots.items():
            try:
                bot_setting = self.bot_caller.bot_load_setting(bot_type)
                bot.when_init(self.bot_caller, bot_setting)
            except Exception as e:
                log_err(f"fail to init bot: {bot_type} err: {e}")


class ActionToolItem(ActionToolItemBase):
    type: str = "object"
    call: str
    description: str
    request: Any
    execute: constr(regex="system|AI")


class ActionCall(BaseModel):
    brief: str = ""
    action: ActionToolItem
    chat_from: Any = None


class ExternAction:
    action_path: str = "./aimi_plugin/action/"
    action_call_prefix: str = "chat_to_"
    action_offset: int = 0
    actions: Dict[str, ActionCall] = {}

    def __init__(self, action_path: str):
        self.action_path = action_path
        self.__load_extern_action()

    def brief(self) -> List[ActionToolItem]:
        cnt = 0
        catalog = []
        for call, action_call in self.actions.items():
            # 计算显示偏移 只有数量足够多才需要滑动
            if len(self.actions) - self.action_offset > 10:
                cnt += 1
                if cnt < self.action_offset:
                    continue

                if len(catalog) >= 10:
                    break
            catalog.append(action_call.action)

        return catalog

    def __append_extern_action(self, action: ActionToolItem, chat_from: Any = None):
        action_brief = action.description
        # 只挑选 前面部分作为简介
        brief_idx = action_brief.find(":")
        if brief_idx != -1 and brief_idx < 15:
            action_brief = action_brief[:brief_idx]

        self.actions[action.call] = ActionCall(
            action=action,
            brief=action_brief,
            chat_from=chat_from,
        )

    def __load_extern_action(self):
        # 指定目录路径
        for filename, module in load_module(
            module_path=self.action_path,
            load_name=["s_action"],
            file_start=self.action_call_prefix,
        ):
            if filename == f"{self.action_call_prefix}example.py":
                continue

            try:
                action: ActionToolItem = module.s_action
                action_call = filename.replace(".py", "")
                action.call = action_call

                # log_dbg(f"action: {json.dumps(action.dict(), indent=4, ensure_ascii=False)}")

                chat_from = None
                if hasattr(module, "chat_from"):
                    chat_from = module.chat_from

                self.__append_extern_action(action, chat_from)

                log_info(f"load action: {action_call}")

            except Exception as e:
                log_err(f"fail to load {filename} : {str(e)}")

    def save_action(
        self,
        action: ActionToolItem,
        save_action_example: str,
        save_action_code: str = None,
    ):
        response = ""
        if action.call in self.actions:
            response = f"fail to save call: {action.call}, arealy exsit."
            log_err(response)
            return False, response

        if save_action_code:
            save_action_example += save_action_code
            log_dbg(f"append chat_from code:\n```python\n{save_action_code}\n```")

        if self.action_call_prefix in action.call:
            action.call = action.call.replace(self.action_call_prefix, "")
            log_err(f"fix action call chat_to_ prefix")

        action.call = f"{self.action_call_prefix}{action.call}"

        try:
            save_filename = f"{action.call}.py"
            file = open(
                f"{self.action_path}/tmp/{save_filename}",
                "w",
                encoding="utf-8",
            )
            file.write(save_action_example)
            file.close()

            log_dbg(f"write action: {action.call} done")

            chat_from = None
            if save_action_code:
                for filename, module in load_module(
                    module_path=self.action_path, load_name=["chat_from"]
                ):
                    if filename != save_filename:
                        continue

                    chat_from = module.chat_from
            if save_action_code and not chat_from:
                raise Exception(
                    f"save failed: you need to set the function name to chat_form"
                )

            shutil.move(
                f"{self.action_path}/tmp/{save_filename}",
                f"{self.action_path}/{save_filename}",
            )

            self.__append_extern_action(action, chat_from)

            return True, "save done"
        except Exception as e:
            response = f"fail to save {action.call} : {str(e)}"
            log_err(response)
        return False, response


class AimiPlugin:
    bot_path: str = ""
    action_path: str = ""
    setting: Dict
    chatbot: ChatBot
    extern_action: ExternAction

    def __init__(self, setting):
        self.__load_setting(setting)

        self.chatbot = ChatBot(self.bot_path)
        self.extern_action = ExternAction(self.action_path)

        self.chatbot.when_init()

    def __load_setting(self, setting):
        self.setting = setting

        try:
            self.bot_path = setting["bot_path"]
        except Exception as e:
            log_err(f"fail to get bot_path: {e}")
            self.bot_path = "./aimi_plugin/bot"

        try:
            self.action_path = setting["action_path"]
        except Exception as e:
            log_err(f"fail to get action_path: {e}")
            self.action_path = "./aimi_plugin/action"

    def when_exit(self):
        self.chatbot.when_exit()
