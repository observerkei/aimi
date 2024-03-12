import atexit
import signal
import threading
import time
import random
from typing import Generator, List, Dict, Any, Tuple
from contextlib import suppress

from tool.config import Config
from tool.util import log_dbg, log_err, log_info, make_context_messages
from core.aimi_plugin import AimiPlugin, Bot, ChatBot, ChatBotType, BotAskData
from app.app_qq import ChatQQ
from app.app_web import ChatWeb

from tool.md2img import Md
from core.memory import Memory
from core.task import Task


class ReplyStep:
    class TalkList:
        has_start: bool = False
        now_list_line_cnt: int = 0
        list_line_cnt_max: int = 0
        now_list_id: int = 0
        cul_line_cnt_max: bool = True

        def check_talk_list(self, line: str) -> bool:
            if self.now_list_line_cnt < self.list_line_cnt_max:
                self.now_list_line_cnt += 1
                return True

            # 刚好下一个下标过来了
            next_list_id_str = "{}. ".format(self.now_list_id + 1)
            next_list_id_ch_str = "{}。 ".format(self.now_list_id + 1)
            next_list_id_bing_str = "[{}]: ".format(self.now_list_id + 1)
            if (
                (next_list_id_str in line)
                or (next_list_id_ch_str in line)
                or (next_list_id_bing_str in line)
            ):
                log_dbg("check talk list[{}]".format(self.now_list_id))
                self.now_list_line_cnt = 0
                self.now_list_id += 1
                return True

            return False

        def reset(self):
            self.has_start = False
            self.now_list_line_cnt = 0
            self.list_line_cnt_max = 0
            self.now_list_id = 0
            self.cul_line_cnt_max = True

        def is_talk_list(self, line: str):
            # 有找到开始的序号
            if (not self.has_start) and (
                ("1. " in line) or ("1。 " in line) or ("[1]: " in line)
            ):
                self.has_start = True
                self.now_list_line_cnt = 1
                self.list_line_cnt_max = 1
                self.now_list_id = 1
                return True

            # 标记过才处理
            if not self.has_start:
                return False

            if "\n" == line:
                return True

            # 已经找到当前每行的长度
            if not self.cul_line_cnt_max:
                ret = self.check_talk_list(line)
                if not ret:
                    self.reset()
                return ret

            if (self.now_list_id) and (
                ("2. " in line) or ("2。 " in line) or ("[2]: " in line)
            ):
                self.now_list_id = 2
                self.now_list_line_cnt = 0
                self.cul_line_cnt_max = False
                ret = self.check_talk_list(line)
                if not ret:
                    self.reset()
                return ret

            # 统计每块最大行
            self.list_line_cnt_max += 1
            return True

    class MathList:
        has_start: bool = False

        def __is_math_format(md: Md, line: str) -> bool:
            if "=" in line:
                return True
            if md.has_latex(line):
                log_dbg("match: is latex")
                return True
            if md.has_html(line):
                log_dbg("match: is html")
                return True
            return False

        def is_math_list(self, md: Md, line: str) -> bool:
            if self.__is_math_format(md, line):
                self.has_start = True
                return True

            if not self.has_start:
                return False

            if "\n" == line:
                return True

            self.has_start = False
            return False


class Aimi:
    type: str = "Aimi"
    timeout: int = 360
    master_name: str = ""
    aimi_name: str = "Aimi"
    preset_facts: Dict[str, str] = {}
    max_link_think: int = 1024
    running: bool = True
    api: List[str] = []
    config: Config
    md: Md
    memory: Memory
    task: Task
    task_setting: Dict = {}
    aimi_plugin: AimiPlugin
    chat_web: ChatWeb
    chat_qq: ChatQQ
    chatbot: ChatBot

    def __init__(self):
        self.__load_setting()
        self.config = Config()
        self.md = Md()
        self.memory = Memory()

        self.aimi_plugin = AimiPlugin(self.aimi_plugin_setting)
        self.task = Task(self.aimi_plugin, self.task_setting)
        
        self.chatbot = self.aimi_plugin.chatbot
        self.chatbot.append(ChatBotType.Task, self.task)

        self.chat_web = ChatWeb()
        self.chat_qq = ChatQQ()

        # 注册意外退出保护记忆
        atexit.register(self.__when_exit)
        signal.signal(signal.SIGTERM, self.__signal_exit)
        signal.signal(signal.SIGINT, self.__signal_exit)

        self.chat_web.register_ask_hook(self.web_ask)
        self.chat_web.models = self.get_all_models()

    def run(self):
        self.notify_online()

        aimi_read = threading.Thread(target=self.read)
        chat_qq_server = threading.Thread(target=self.chat_qq.server)
        chat_web_server = threading.Thread(target=self.chat_web.server)
        aimi_dream = threading.Thread(target=self.memory.dream)

        # 同时退出
        aimi_read.setDaemon(True)
        aimi_dream.setDaemon(True)
        chat_qq_server.setDaemon(True)
        chat_web_server.setDaemon(True)

        aimi_read.start()
        aimi_dream.start()
        chat_qq_server.start()
        chat_web_server.start()

        cnt = 0
        while self.running:
            cnt = cnt + 1
            if cnt < 60:
                time.sleep(1)
                continue
            else:
                cnt = 0

            try:
                if not self.memory.save_memory():
                    log_err("save memory failed")
                if not self.task.save_task():
                    log_err("save task failed")

            except Exception as e:
                log_err("fail to save: " + str(e))

        log_dbg("aimi exit")

    def __get_api_type_by_question(self, question: str) -> str:
        for bot_type, bot in self.chatbot.each_bot():
            if not bot.init:
                continue

            ask_data = BotAskData(question=question)
            if bot.is_call(self.chatbot.bot_caller, ask_data):
                return bot_type

        if self.chatbot.has_bot_init(ChatBotType.Task):
            return ChatBotType.Task

        # 一个都找不到，随机取一个.
        for bot_type, bot in self.chatbot.each_bot():
            if not bot.init:
                continue
            return bot_type

        return ""

    @property
    def __busy_reply(self) -> str:
        busy = [
            "让我想想...",
            "......",
            "那个...",
            "这个...",
            "?",
            "喵喵喵？",
            "*和未知敌人战斗中*",
            "*大脑宕机*",
            "*大脑停止响应*",
            "*尝试构造语言中*",
            "*被神秘射线击中,尝试恢复中*",
            "*猫猫叹气*",
        ]
        return random.choice(busy)

    def read(self):
        while self.running:
            if not self.chat_qq.has_message():
                time.sleep(1)
                continue

            for msg in self.chat_qq:
                log_info("recv msg, try analyse")
                nickname = self.chat_qq.get_name(msg)
                question = self.chat_qq.get_question(msg)
                log_info("{}: {}".format(nickname, question))

                api_type = self.__get_api_type_by_question(question)

                reply = ""
                reply_line = ""
                reply_div = ""
                answer = {}

                talk_list = ReplyStep.TalkList()
                math_list = ReplyStep.MathList()
                code = 0
                for answer in self.ask(question, nickname):
                    code = answer["code"]

                    message = answer["message"][len(reply) :]
                    reply_line += message

                    reply = answer["message"]

                    reply_div_len = len(reply_div)
                    log_dbg(
                        f"code: {str(code)} div: {str(reply_div_len)} line: {str(reply_line)}"
                    )

                    if code == 0 and (
                        len(reply_div) or ((not len(reply_div)) and len(reply_line))
                    ):
                        reply_div += reply_line
                        reply_line = ""

                        reply_div = self.reply_adjust(reply_div, api_type)
                        log_dbg(f"send div: {str(reply_div)}")
                        self.chat_qq.reply_question(msg, reply_div)

                        break
                    if (code == -1) and (len(reply_div) or len(reply_line)):
                        if not len(reply_div):
                            reply_div = self.__busy_reply
                        reply_div = self.reply_adjust(reply_div, api_type)
                        log_dbg(f"fail: {str(reply_line)}, send div: {str(reply_div)}")
                        self.chat_qq.reply_question(msg, reply_div)
                        reply_line = ""
                        reply_div = ""
                        continue

                    if code != 1:
                        continue

                    if "\n" in reply_line:
                        if talk_list.is_talk_list(reply_line):
                            reply_div += reply_line
                            reply_line = ""
                            continue
                        elif math_list.is_math_list(self.md, reply_line):
                            reply_div += reply_line
                            reply_line = ""
                            continue
                        elif not len(reply_div):
                            # first line.
                            reply_div += reply_line
                            reply_line = ""

                        reply_div = self.reply_adjust(reply_div, api_type)

                        log_dbg("send div: " + str(reply_div))

                        self.chat_qq.reply_question(msg, reply_div)

                        # 把满足规则的先发送，然后再保存新的行。
                        reply_div = reply_line
                        reply_line = ""

                log_dbg(f"answer: {str(type(answer))} {str(answer)}")
                reply = self.reply_adjust(reply, api_type)
                log_dbg(f"adjust: {str(reply)}")

                log_info(f"{nickname}: {question}")
                log_info(f"{self.aimi_name}: {str(reply)}")

                if code == 0:
                    pass  # self.chat_qq.reply_question(msg, reply)

                # server failed
                if code == -1:
                    meme_err = self.config.meme.error
                    img_meme_err = self.chat_qq.get_image_message(meme_err)
                    self.chat_qq.reply_question(msg, "server unknow error :(")
                    self.chat_qq.reply_question(msg, img_meme_err)

                # trans text to img
                if self.md.need_set_img(reply):
                    log_info("msg need set img")
                    img_file = self.md.message_to_img(reply)
                    cq_img = self.chat_qq.get_image_message(img_file)

                    self.chat_qq.reply_question(msg, cq_img)

    def reply_adjust(self, reply: str, res_api: str) -> str:
        if res_api == ChatBotType.Bing:
            reply = reply.replace("必应", f" {self.aimi_name}通过必应得知: ")
            reply = reply.replace("你好", " Master你好 ")
            reply = reply.replace("您好", " Master您好 ")

        return reply

    def web_ask(
        self,
        question: str,
        nickname: str = None,
        model: str = "auto",
        api_key: str = "",
        owned_by: str = "Aimi",
        context_messages: Any = None,
    ) -> Generator[dict, None, None]:
        preset = context_messages[0]["content"]
        api_type = owned_by

        if api_type == self.aimi_name and ChatBotType.Task in model:
            api_type = ChatBotType.Task

        nickname = nickname if nickname and len(nickname) else self.master_name

        talk_history = context_messages[1:-1]

        ask_data = BotAskData(
            question=question,
            model=model,
            api_key=api_key,
            aimi_name=self.aimi_name,
            preset=preset,
            nickname=nickname,
            messages=context_messages,
            conversation_id=self.memory.openai_conversation_id,
        )

        if (api_type == self.aimi_name):
            return self.ask(
                question=question, preset=preset, ask_data=ask_data
            )
        else:
            ask_data.history = self.memory.make_history(talk_history)
            return self.__post_question(
                api_type=api_type,
                ask_data=ask_data,
            )

    def ask(
        self, question: str, preset: str, ask_data: BotAskData, talk_history 
    ) -> Generator[dict, None, None]:
        api_type = self.__get_api_type_by_question(question)

        if preset.isspace():
            with suppress(KeyError):
                preset = self.preset_facts[api_type]

        talk_history = self.memory.search(question, self.max_link_think)
        ask_data.messages = make_context_messages(question, preset, talk_history)

        history = self.memory.make_history(talk_history)
        ask_data.history = history

        for message in self.__post_question(
            api_type=api_type,
            ask_data=ask_data,
        ):
            if not message:
                continue
            # log_dbg(f'message: {str(type(message))} {str(message)} answer: {str(type(answer))} {str(answer))}'

            # save self.memory
            if message["code"] == 0:
                self.memory.append(q=question, a=message["message"])

            yield message

    def __post_question(
        self, api_type: str, ask_data: BotAskData
    ) -> Generator[dict, None, None]:
        log_dbg("use api: " + str(api_type))

        if api_type == ChatBotType.OpenAI:
            yield from self.__post_openai(ask_data)
        elif self.chatbot.has_type(api_type):
            yield from self.chatbot.ask(api_type, ask_data)
        else:
            log_err("not suppurt api_type: " + str(api_type))

    def __post_openai(self, ask_data: BotAskData) -> Generator[dict, None, None]:

        answer = self.chatbot.ask(ChatBotType.OpenAI, ask_data)
        # get yield last val
        for message in answer:
            # log_dbg('now msg: ' + str(message))

            try:
                if (
                    message
                    and message["code"] == 0
                    and message["conversation_id"]
                    and message["conversation_id"] != self.memory.openai_conversation_id
                ):
                    self.memory.openai_conversation_id = message["conversation_id"]
                    log_info(
                        "set new con_id: " + str(self.memory.openai_conversation_id)
                    )
            except Exception as e:
                log_dbg(f"no conv_id")

            yield message

    def get_all_models(self) -> Dict[str, List[str]]:
        bot_models: Dict[str, List[str]] = {}

        aimi_models: List = []
        for bot_type, bot in self.chatbot.each_bot():
            if bot.init:
                continue
            aimi_models.append("auto")
            break

        if self.task.init:
            for m in self.task.models:
                aimi_models.append(m)

        if len(aimi_models):
            bot_models[self.aimi_name] = aimi_models

        for bot_type, bot in self.chatbot.each_bot():
            if not bot.init:
                continue
            if ChatBotType.Task == bot_type:
                continue
            models = bot.get_models(self.chatbot.bot_caller)
            bot_models[bot_type] = models

        return bot_models

    def __load_setting(self):
        try:
            setting = Config.load_setting("aimi")
        except Exception as e:
            log_err(f"fail to load {self.type}: {e}")
            setting = {}
            return

        try:
            self.aimi_name = setting["name"]
        except Exception as e:
            log_err("fail to load aimi: {e}")
            self.aimi_name = "Aimi"
        try:
            self.aimi_plugin_setting = setting["aimi_plugin"]
        except Exception as e:
            log_err("fail to load aimi: {e}")
            self.aimi_plugin_setting = {}

        try:
            self.task_setting = setting["task"]
        except Exception as e:
            log_err("fail to load aimi: {e}")
            self.task_setting = {}

        try:
            self.master_name = setting["master_name"]
        except Exception as e:
            log_err("fail to load aimi: {e}")
            self.master_name = ""

        try:
            self.api = setting["api"]
        except Exception as e:
            log_err("fail to load aimi api: " + str(e))
            self.api = []

        try:
            self.preset_facts = {}
            for api in self.api:
                try:
                    preset_facts: List[str] = setting["preset_facts"][api]
                except Exception as e:
                    log_info(f"no {api} type preset, skip.")
                    continue

                self.preset_facts[api] = ""
                count = 0
                for fact in preset_facts:
                    fact = fact.replace("<name>", self.aimi_name)
                    fact = fact.replace("<master>", self.master_name)
                    count += 1
                    if count != len(preset_facts):
                        fact += "\n"
                    self.preset_facts[api] += fact

            self.preset_facts["default"] = self.preset_facts[self.api[0]]
        except Exception as e:
            log_err("fail to load aimi preset: " + str(e))
            self.preset_facts = {}

    def notify_online(self):
        if not self.chat_qq.is_online():
            log_err(f"{self.chat_qq.type} offline")
            return
        self.chat_qq.reply_online()

    def notify_offline(self):
        self.chat_qq.reply_offline()

    def __signal_exit(self, sig, e):
        log_info("recv exit sig.")
        self.running = False
        self.chat_qq.stop()

    def __when_exit(self):
        self.running = False

        log_info("now exit aimi.")
        self.notify_offline()

        if self.memory.save_memory():
            log_info("exit: save self.memory done.")
        else:
            log_err("exit: fail to save self.memory.")

        if self.task.save_task():
            log_info("exit: save task done.")
        else:
            log_err("exit: fail to task self.memory.")

        try:
            self.aimi_plugin.when_exit()
        except Exception as e:
            log_err(f"fail to exit aimi plugin: {e}")
