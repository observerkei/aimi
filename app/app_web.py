from flask import (
    Flask,
    request,
    render_template,
    stream_with_context,
    Response,
    make_response,
)
from flask_cors import CORS
import json
from typing import Any, List, Dict
from pydantic import BaseModel

from tool.util import log_info, log_err, log_dbg
from core.session import Session

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


class AppWEB:
    api_host: str = "localhost"
    api_port: int = 4642
    app: Any
    http_server: Any
    ask_hook: Any
    models: Dict
    session: Session
    get_all_models_hook: Any

    def __init__(self, session, ask, get_all_models):
        self.session = session
        self.ask_hook = ask
        self.get_all_models_hook = get_all_models
        self.__listen_init()
        log_dbg("web init done")

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

    def __make_stream_reply(self, reply: str, index: int = 0) -> str:
        stream = {
            "choices": [
                {
                    "delta": {
                        "content": str(reply),
                    },
                    "finish_reason": None,
                    "index": index,
                }
            ],
            "created": 1677825464,
            "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
            "model": "gpt-3.5-turbo-0301",
            "object": "chat.completion.chunk",
        }
        return "event: message\ndata:" + json.dumps(stream) + "\n\n"

    def __make_stream_stop(self, index: int = 0) -> str:
        stream = {
            "choices": [{"delta": {}, "finish_reason": "stop", "index": index}],
            "created": 1677825464,
            "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
            "model": "gpt-3.5-turbo-0301",
            "object": "chat.completion.chunk",
        }
        return "event: message\ndata:" + json.dumps(stream) + "\n\n"

    def __listen_init(self):
        self.app = Flask(__name__)
        # 允许浏览器跨域请求 
        CORS(self.app, resources={r"/v1/*": {"origins": "*", "supports_credentials": True}})


        @self.app.route("/v1/models", methods=["GET"])
        def handle_get_models_request():
            url = request.url
            resp = make_response()

            api_key = ""
            session_id = ""
            need_update_cookie = True
            body = ""
            try:
                body = request.get_data().decode("utf-8")
                # 获取HTTP头部中的 Authorization 值
                auth_header = request.headers.get("Authorization")
                api_key = auth_header[7:]
                session_id = request.cookies.get("session_id")
            except Exception as e:
                log_err(f"fail to get req info: {e}")

            log_dbg(
                f"Received a get request: session_id={session_id}, "
                f"URL={url}, Headers->Authorization={auth_header}, body={body}"
            )


            session_id, need_update_cookie = self.cul_session_id(session_id=session_id, api_key=api_key)
            if not session_id:
                err = "Cannot create session."
                log_err(f"not session: {err}")
                resp.set_data(err)
                return resp
            
            if need_update_cookie:
                log_dbg(f"Update Browser cookie of session_id.")
                resp.set_cookie("session_id", session_id)
            
            session_api_key = self.session.get_chatbot_setting_api_key(session_id)
            if session_api_key != api_key:
                # 如果 key 发生了变更, 需要更新 key, 但是不替换 sesion id.
                done = self.session.update_session_by_api_key(session_id, api_key)
                if not done:
                    err = "Cannot update session data."
                    log_err(f"Error: {err}")
                    resp.set_data(err)
                    return resp

            modelsObj = ""
            try:
                model_infos = []
                all_models = self.get_all_models_hook(session_id)
                if not len(all_models):
                    raise Exception("Cannot get models.")

                for owned_by, models in all_models.items():
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
            resp.set_data(str(modelsObj))

            return resp

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
        def handle_post_api_make_response():
            def event_stream(
                session_id: str,
                question: str,
                model: str,
                api_key: str,
                owned_by: str,
                context_messages: List[Dict],
            ):
                log_dbg(f"wait ask stream.")
                index = 0
                if not len(question):
                    yield self.__make_stream_reply("question is empty.", index)
                    index += 1
                    yield self.__make_stream_stop(index)
                    index += 1
                    yield "event: end\ndata: [DONE]\n\n"
                    return

                prev_text = ""

                for answer in self.ask_hook(
                    session_id,
                    question,
                    None,
                    model,
                    api_key,
                    owned_by,
                    context_messages,
                ):
                    message = answer["message"][len(prev_text) :]
                    yield self.__make_stream_reply(message, index)
                    index += 1
                    if answer["code"] == -1:
                        yield self.__make_stream_reply("\n\n")
                        index += 1
                    prev_text = answer["message"]

                yield self.__make_stream_stop()
                index += 1
                yield "event: end\ndata: [DONE]\n\n"

            url = ""
            api_key = ""
            session_id = ""
            body = ""
            need_update_cookie = True

            # 获取HTTP头部中的 Authorization 值
            try:
                url = request.url
                body = request.get_data().decode("utf-8")
                log_dbg(f"Received a api request: \nURL={url} \nbody={body}")

                authorization = request.headers.get("Authorization")
                api_key = authorization[7:]
                session_id = request.cookies.get("session_id")
                # 调试用, 上线不要打印出来
                log_dbg(f"Key: {api_key}")

            except Exception as e:
                error_message = f"request failed: {str(e)}"
                log_err(error_message)
                # 创建错误响应
                response = make_response(error_message)
                response.status_code = 400  # 设置状态码为400 (Bad Request)

                return response

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
            
            session_id, need_update_cookie = self.cul_session_id(session_id=session_id, api_key=api_key)
            if not session_id:
                err = "Cannot create session."
                log_err(f"not session: {err}")
                return make_response(err)
            
            session_api_key = self.session.get_chatbot_setting_api_key(session_id)
            if session_api_key != api_key:
                # 如果 key 发生了变更, 需要更新 key, 但是不替换 sesion id.
                done = self.session.update_session_by_api_key(session_id, api_key)
                if done:
                    err = "Cannot update session data."
                    log_err(f"Error: {err}")
                    return make_response(err)

            resp = Response(
                event_stream(
                    session_id=session_id,
                    question=question,
                    model=model,
                    api_key=api_key,
                    owned_by=owned_by,
                    context_messages=context_messages,
                ),
                mimetype="text/event-stream",
            )
            
            if need_update_cookie:
                log_dbg(f"Update Browser cookie of session_id.")
                resp.set_cookie("session_id", session_id)

            return resp
    
    def cul_session_id(self, session_id, api_key):
        need_update_cookie = True
        if not session_id or not len(session_id) or not self.session.has_session(session_id):
            # 浏览器提供的 session_id 不可用
            need_update_cookie = True

            # 重新通过key计算 session_id
            new_setting = self.session.dup_setting(api_key)
            session_id = self.session.new_session(api_key, new_setting)
            
        else:
            need_update_cookie = False
        
        return session_id, need_update_cookie

    def server(self):
        from gevent import pywsgi

        self.http_server = pywsgi.WSGIServer(
            listener=(self.api_host, self.api_port), application=self.app, log=None
        )

        log_info("web start")

        self.http_server.serve_forever()
