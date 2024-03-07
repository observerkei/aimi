from flask import Flask, request, render_template, Response
from flask_cors import CORS
import json
import threading
import time
from typing import Any, List, Dict
from pydantic import BaseModel

from tool.util import log_info, log_err, log_dbg

openai_stream_response = [
    {
        "choices": [
            {"delta": {"role": "assistant"}, "finish_reason": None, "index": 0}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [
            {"delta": {"content": "Master "}, "finish_reason": None, "index": 1}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [{"delta": {"content": "~ "}, "finish_reason": None, "index": 2}],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [{"delta": {}, "finish_reason": "stop", "index": 3}],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
]


class ModelInfoPermission(BaseModel):
    id: str
    object: str
    created: int
    allow_create_engine: bool
    allow_sampling: bool
    allow_logprobs: bool
    allow_search_indices: bool
    allow_view: bool
    allow_fine_tuning: bool
    organization: str
    group: Any
    is_blocking: bool


class ModelInfo(BaseModel):
    id: str
    object: str
    created: int
    root: str
    parent: Any
    owned_by: str
    permission: ModelInfoPermission


class Models(BaseModel):
    object: str
    data: List[ModelInfo]


class ChatWeb:
    api_host: str = "localhost"
    api_port: int = 4642
    app: Any
    http_server: Any
    ask_hook: Any
    models: Dict

    def __init__(self):
        self.__listen_init()
        log_dbg("web init done")

    def register_ask_hook(self, ask_hook: Any):
        self.ask_hook = ask_hook

    def __make_model_info(self, model, owned_by) -> ModelInfo:
        def __make_model_info_permission() -> ModelInfoPermission:
            return ModelInfoPermission(
                id="",
                object="",
                created=0,
                allow_create_engine=False,
                allow_sampling=True,
                allow_logprobs=True,
                allow_search_indices=False,
                allow_view=True,
                allow_fine_tuning=False,
                organization="*",
                group=None,
                is_blocking=False,
            )

        mod = ModelInfo(
            id=model,
            object="model",
            created=0,
            root=model,
            parent=None,
            owned_by=owned_by,
            permission=__make_model_info_permission(),
        )
        mod.id = model

        return mod

    def __make_models(self, models: List[ModelInfo]) -> Models:
        return Models(object="list", data=models)

    def __make_stream_reply(self, reply: str) -> str:
        stream = {
            "choices": [
                {
                    "delta": {
                        "content": str(reply),
                    },
                    "finish_reason": None,
                    "index": 2,
                }
            ],
            "created": 1677825464,
            "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
            "model": "gpt-3.5-turbo-0301",
            "object": "chat.completion.chunk",
        }
        return "event: message\ndata:" + json.dumps(stream) + "\n\n"

    def __make_stream_stop(self) -> str:
        stream = {
            "choices": [{"delta": {}, "finish_reason": "stop", "index": 2}],
            "created": 1677825464,
            "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
            "model": "gpt-3.5-turbo-0301",
            "object": "chat.completion.chunk",
        }
        return "event: message\ndata:" + json.dumps(stream) + "\n\n"

    def __listen_init(self):
        self.app = Flask(__name__)
        CORS(self.app)

        @self.app.route("/v1/models", methods=["GET"])
        def handle_get_models_request():
            url = request.url
            auth_header = ""
            body = ""
            try:
                body = request.get_data().decode("utf-8")
                # 获取HTTP头部中的 Authorization 值
                auth_header = request.headers.get("Authorization")

            except:
                pass
            log_dbg(
                f"Received a get request: URL={url}, Authorization={auth_header}, body={body}"
            )

            modelsObj = ""
            try:
                model_infos = []
                for owned_by, models in self.models.items():
                    for model in models:
                        model_info = self.__make_model_info(
                            f"{owned_by}--{model}", owned_by
                        )
                        model_infos.append(model_info)
                        # log_dbg(f"mod: {str(model)} owned_by: {str(owned_by)}")

                models = self.__make_models(model_infos)
                # log_dbg(f"models: {str(models)}")

                modelsObj = models.json()

            except Exception as e:
                log_err(f"{e}")

            # log_dbg(f"models obj: f{str(modelsObj)}")

            return str(modelsObj)

        @self.app.route("/", methods=["POST"])
        def handle_post_index_request():
            url = request.url
            body = ""
            try:
                body = request.get_data().decode("utf-8")
            except:
                pass
            log_dbg(f"Received a post index request: URL={url}, body={body}")

            return "ok"

        @self.app.route("/v1/chat/completions", methods=["POST"])
        def handle_post_api_request():
            def event_stream(
                question: str, model: str, owned_by: str, context_messages: List[Dict]
            ):
                if not len(question):
                    yield self.__make_stream_reply("question is empty.")
                    yield self.__make_stream_stop()
                    yield "event: end\ndata: [DONE]\n\n"
                    return

                prev_text = ""

                for answer in self.ask_hook(
                    question, None, model, owned_by, context_messages
                ):
                    message = answer["message"][len(prev_text) :]
                    yield self.__make_stream_reply(message)
                    if answer["code"] == -1:
                        yield self.__make_stream_reply("\n\n")
                    prev_text = answer["message"]

                yield self.__make_stream_stop()
                yield "event: end\ndata: [DONE]\n\n"

            url = request.url
            body = request.get_data().decode("utf-8")
            log_dbg(f"Received a api request: URL={url}, body={body}")

            question = ""
            model = ""
            owned_by = ""
            context_messages = []
            try:
                # 将json字符串转化为json数据
                web_request = json.loads(body)

                # 获取message数组的最后一条数据
                context_messages = web_request["messages"]
                last_message = context_messages[-1]
                question = last_message["content"]
                log_dbg(f"get question: {question}")

                # get model
                model = web_request["model"]
                owned_by = ""
                if "owned_by" in web_request:
                    owned_by = web_request["owned_by"]

                model_info = model.split("--")
                if len(model_info) == 2:
                    owned_by = model_info[0]
                    model = model_info[1]

                log_dbg(f"use model: {model}")
                log_dbg(f"model owned_by: {owned_by}")
            except Exception as e:
                log_err(f"fail to get requestion: {e}")
                model = "auto"
                owned_by = "Aimi"

            # 返回该响应
            return Response(
                event_stream(question, model, owned_by, context_messages),
                mimetype="text/event-stream",
            )

    def server(self):
        from gevent import pywsgi

        self.http_server = pywsgi.WSGIServer(
            listener=(self.api_host, self.api_port), application=self.app, log=None
        )

        log_info("web start")

        self.http_server.serve_forever()
