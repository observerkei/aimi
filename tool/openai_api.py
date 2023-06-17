import time
from typing import Generator, List, Dict, Any
import openai

from tool.util import log_dbg, log_err, log_info
from tool.config import Config


class OpenAIAPI:
    type: str = "openai"
    chatbot: Any
    use_web_ask: bool = False
    max_requestion: int = 1024
    access_token: str = ""
    max_repeat_times: int = 3
    fackopen_url: str = ""
    api_key: str
    api_base: str
    trigger: List[str] = []
    model: str = ""
    models: List[str] = []
    default_model: str = "gpt-3.5-turbo"
    chat_completions_models: List[str] = [
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-0301",
        "gpt-3.5-turbo-0613	",
        "gpt-3.5-turbo-16k",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4",
        "gpt-4-0314",
        "gpt-4-0613",
        "gpt-4-32k",
        "gpt-4-32k-0314",
        "gpt-4-32k-0613",
    ]
    init: bool = False

    class InputType:
        SYSTEM = "system"
        USER = "user"
        ASSISTANT = "assistant"

    def is_call(self, question) -> bool:
        for call in self.trigger:
            if call.lower() in question.lower():
                return True

        return False

    def get_models(self) -> List[str]:
        if not self.init:
            return []

        return self.models

    def ask(
        self,
        question: str,
        model: str = "",
        context_messages: List[Dict] = [],
        conversation_id: str = "",
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        if self.use_web_ask:
            yield from self.web_ask(question, conversation_id, timeout)
        else:
            yield from self.api_ask(question, model, context_messages, timeout)

    def web_ask(
        self,
        question: str,
        conversation_id: str = "",
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = {"message": "", "conversation_id": conversation_id, "code": 1}

        model = self.model if self.model and len(self.model) else None

        req_cnt = 0

        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            answer["code"] = 1

            try:
                log_dbg("try ask: " + str(question))

                if conversation_id and len(conversation_id):
                    for data in self.chatbot.ask(
                        question,
                        conversation_id,
                        parent_id=None,
                        model=model,
                        auto_continue=False,
                        timeout=timeout,
                    ):
                        answer["message"] = data["message"]
                        yield answer
                else:
                    for data in self.chatbot.ask(
                        question, None, None, None, timeout=480
                    ):
                        answer["message"] = data["message"]
                        yield answer

                    answer["conversation_id"] = self.get_revChatGPT_conversation_id()

                answer["code"] = 0
                yield answer

            except Exception as e:
                log_err("fail to ask: " + str(e))
                log_info("server fail, sleep 30")
                time.sleep(30)

                answer["message"] = str(e)
                answer["code"] = -1
                yield answer

            # request complate.
            if answer["code"] == 0:
                break

    def __get_bot_model(self, question: str) -> str:
        return self.default_model

    def api_ask(
        self,
        question: str,
        bot_model: str = "",
        messages: List[Dict] = [],
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = {"message": "", "code": 1}

        # yield
        #   "message": 'not support api!',
        #   "conversation_id": conversation_id,
        #   "code": -1
        # }

        req_cnt = 0
        if not bot_model or not len(bot_model) or (
            bot_model not in self.chat_completions_models
        ):
            bot_model = self.__get_bot_model(question)
        log_dbg(f"use model: {bot_model}")
        log_dbg(f"msg: {str(messages)}")

        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            answer["code"] = 1

            try:
                log_dbg("try ask: " + str(question))
                res = None

                completion = {"role": "", "content": ""}
                for event in openai.ChatCompletion.create(
                    model=bot_model,
                    messages=messages,
                    stream=True,
                ):
                    if event["choices"][0]["finish_reason"] == "stop":
                        # log_dbg(f'recv complate: {completion}')
                        break
                    for delta_k, delta_v in event["choices"][0]["delta"].items():
                        if delta_k != "content":
                            # skip none content
                            continue
                        # log_dbg(f'recv stream: {delta_k} = {delta_v}')
                        completion[delta_k] += delta_v

                        answer["message"] = completion[delta_k]
                        yield answer

                    res = event

                log_dbg(f"res: {str(res)}")

                answer["code"] = 0
                yield answer

            except Exception as e:
                log_err("fail to ask: " + str(e))
                log_info("server fail, sleep 15")
                time.sleep(15)
                # log_info(f"try recreate {self.type} bot")
                # self.__create_bot()

                answer["message"] = str(e)
                answer["code"] = -1
                yield answer

            # request complate.
            if answer["code"] == 0:
                break

    def get_revChatGPT_conversation_id(self) -> str:
        conv_li = self.chatbot.get_conversations(0, 1)
        try:
            return conv_li[0]["id"]
        except:
            return ""

    def __init__(self) -> None:
        self.__load_setting()
        self.__create_bot()

    def __create_bot(self) -> bool:
        access_token = self.access_token
        if access_token and len(access_token):
            from revChatGPT.V1 import Chatbot

            # 这个库有封号风险, 设置才导入这个包.

            self.chatbot = Chatbot({"access_token": access_token})
            self.use_web_ask = True

            # set revChatGPT fackopen_url
            fackopen_url = self.fackopen_url
            if fackopen_url and len(fackopen_url):
                self.chatbot.BASE_URL = fackopen_url
                log_info("use fackopen_url: " + str(fackopen_url))

            self.init = True

        api_base = self.api_base
        if api_base and len(api_base):
            openai.api_base = api_base
            log_dbg(f"use openai base: {api_base}")

        api_key = self.api_key
        if api_key and len(api_key):
            openai.api_key = api_key
            try:
                models = openai.Model.list(model_type="chat")
                for model in models["data"]:
                    if not (model.id in self.chat_completions_models):
                        continue
                    log_dbg(f"avalible model: {str(model.id)}")
                    self.models.append(model.id)

                self.init = True
                self.use_web_ask = False
            except Exception as e:
                log_err(f"fail to get model {self.type} : {e}")

        if not self.init:
            try:
                hello = "状态正常?请回答‘是’或‘否’."
                bot_model = self.__get_bot_model(hello)
                for event in openai.ChatCompletion.create(
                    model=bot_model,
                    messages=[{"role": "user", "content": hello}],
                    stream=True,
                ):
                    if event["choices"][0]["finish_reason"] == "stop":
                        # log_dbg(f'recv complate: {completion}')
                        break
                    log_dbg(f"{str(event)}")

                self.models.append(bot_model)
                self.init = True
                self.use_web_ask = False
            except Exception as e:
                log_err(f"fail to ask {self.type}: {e}")

        return self.init

    def __load_setting(self):
        try:
            setting = Config.load_setting(self.type)
        except Exception as e:
            log_err(f"fail to load {self.type}: {e}")
            setting = {}
            return

        try:
            self.max_requestion = setting["max_requestion"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.max_requestion = 1024
        try:
            self.access_token = setting["access_token"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.access_token = ""
        try:
            self.max_repeat_times = setting["max_repeat_times"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.max_repeat_times = 3
        try:
            self.fackopen_url = setting["fackopen_url"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.fackopen_url = ""
        try:
            self.model = setting["model"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.model = ""
        try:
            self.trigger = setting["trigger"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.trigger = ["@openai", "#openai"]
        try:
            self.api_base = setting["api_base"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.api_base = ""
        try:
            self.api_key = setting["api_key"]
        except Exception as e:
            log_err(f"fail to load {self.type} config: " + str(e))
            self.api_key = ""


openai_api = OpenAIAPI()
