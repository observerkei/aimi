import requests

import re
import time
import threading
from typing import Set, Any, Dict, List
from flask import Flask, request, make_response
from pydantic import BaseModel
from urllib import parse

from tool.util import log_dbg, log_err, log_info, read_yaml
from tool.config import Config


class RequestData(BaseModel):
    method: str
    url: str
    headers: dict = None
    data: dict = None


class GoCQHTTP:
    name: str = "go-cqhttp"
    post_host: str = "127.0.0.1"
    post_port: int = 5700
    account_uid: int = 0

    def __init__(self, setting):
        self.__load_go_cqhttp_config(setting)

    def __load_go_cqhttp_config(self, setting: Dict):
        try:
            self.account_uid = setting["uid"]

            post_host = setting["post_host"]
            self.post_host = str(post_host)

            post_port = setting["post_port"]
            self.post_port = int(post_port)

        except Exception as e:
            log_err("fail to get go-cqhttp config: " + str(e))

    def is_message(self, msg) -> bool:
        try:
            post_type = msg["post_type"]
            if post_type == "message":
                return True
            else:
                log_dbg(f"not messge type: {post_type}")
        except:
            log_err("fail to check msg type")
            return False

    def is_private(self, msg) -> bool:
        if not self.is_message(msg):
            return False

        try:
            return msg["message_type"] == "private"
        except:
            log_err("fail to check private type")
            return False

    def is_group(self, msg) -> bool:
        if not self.is_message(msg):
            return False
        try:
            return msg["message_type"] == "group"
        except:
            log_err("failt to check is_group")
            return False

    def get_group_ban(self, group_id: int, user_id: int, duration_time_s: int):
        return f"http://{self.post_host}:{self.post_port}/set_group_ban?group_id={group_id}&user_id={user_id}&duration={duration_time_s}"

    def make_at(self, id: int) -> str:
        return "[CQ:at,qq={}]".format(id)

    def is_at_self(self, message) -> bool:
        at_self = self.make_at(self.account_uid)
        if at_self in message:
            return True
        return False

    def get_name(self, msg) -> str:
        try:
            return msg["sender"]["nickname"]
        except:
            return ""

    def need_filter_question(self, question) -> bool:
        if self.is_at_self(question):
            return True

        del_msg = "请使用最新版手机QQ体验新功能"
        if del_msg in question:
            return True

        return False

    def filter_question(self, question) -> str:
        if self.is_at_self(question):
            log_dbg("question: " + str(question))
            question = re.sub("\[CQ:.*?\]", "", question)
            log_dbg("del at self done: " + str(question))

        del_msg = "请使用最新版手机QQ体验新功能"
        if del_msg in question:
            question = question.replace(del_msg, " ")
            log_dbg("del: " + str(del_msg))

        return question

    def get_message(self, msg) -> str:
        try:
            return msg["message"]
        except:
            return ""

    def get_question(self, msg) -> str:
        question = self.get_message(msg)

        # del qq function content.
        if self.need_filter_question(question):
            log_info("question need filter.")
            question = self.filter_question(question)
            log_dbg("question filter done: " + str(question))

        return question

    def get_user_id(self, msg) -> int:
        try:
            return msg["user_id"]
        except:
            return 0

    def get_group_id(self, msg) -> int:
        try:
            return msg["group_id"]
        except:
            return 0

    def get_image_cq(self, file) -> str:
        return "[CQ:image,file=file://{}]".format(file)

    def make_url_get_qq_info(self) -> str:
        return f"http://{self.post_host}:{self.post_port}/get_login_info"

    def get_reply_private(self, user_id: int, reply: str) -> RequestData:
        reply_quote = parse.quote(reply)

        api_private_reply = (
            "http://{}:{}/send_private_msg?user_id={}&message={}".format(
                self.post_host, self.post_port, user_id, reply_quote
            )
        )
        reply = RequestData(method="GET", url=api_private_reply)

        return reply

    def get_reply_group(self, group_id: int, user_id: int, reply) -> RequestData:
        at_user = ""
        if user_id:
            at_user = self.make_at(user_id) + "\n"
        at_reply = at_user + reply

        reply_quote = parse.quote(at_reply)

        at_reply_quote = reply_quote

        api_group_reply = "http://{}:{}/send_group_msg?group_id={}&message={}".format(
            self.post_host, self.post_port, group_id, at_reply_quote
        )

        reply = RequestData(method="GET", url=api_group_reply)
        return reply


class Shamrock(GoCQHTTP):
    name: str = "shamrock"

    def get_reply_private(self, user_id: int, reply: str) -> RequestData:
        url = f"http://{self.post_host}:{self.post_port}/send_private_msg"
        data = {
            "user_id": int(user_id),
            "message": reply,
        }
        reply = RequestData(method="POST", url=url, data=data)

        return reply

    def get_reply_group(self, group_id: int, user_id: int, reply) -> RequestData:
        at_user = ""
        if user_id:
            at_user = self.make_at(user_id) + "\n"
        at_reply = at_user + reply

        url = f"http://{self.post_host}:{self.post_port}/send_group_msg"
        data = {
            "group_id": int(group_id),
            "message": at_reply,
        }

        reply = RequestData(method="POST", url=url, data=data)
        return reply


class BotManage:
    reply_time: Dict[int, int] = {}
    protect_bot_ids: List[int] = []
    reply_time_limit_s: int = 1
    reply_max_cnt: int = 10  # max reply limit
    reply_cur_cnt: int = 0  # cur reply limit

    def __init__(self):
        self.__load_setting()

        for bot_id in self.protect_bot_ids:
            self.reply_time[bot_id] = 0

    def __load_setting(self):
        try:
            setting = Config.load_setting("qq")
            setting = setting["manage"]
        except Exception as e:
            log_err(f"fail to get qq cfg: {e}")
            return

        try:
            self.protect_bot_ids = setting["protect_bot_ids"]
        except Exception as e:
            log_err(f"fail to load protect_bot_ids: {e}")
            self.protect_bot_ids = []

        try:
            self.reply_time_limit_s = setting["reply_time_limit_s"]
        except Exception as e:
            log_err(f"fail to load reply_time_limit_s: {e}")
            self.reply_time_limit_s = 3600

    def update_reply_time(self, bot_id: int):
        current_time_seconds = int(time.time())
        self.reply_time[bot_id] = current_time_seconds

    def over_reply_time_limit(self, bot_id: int) -> bool:
        if not self.reply_time[bot_id]:
            return True

        current_time_seconds = int(time.time())

        if (self.reply_time[bot_id] + self.reply_time_limit_s) > current_time_seconds:
            log_dbg(f"bot is limit time {self.reply_time_limit_s}")
            return True
        return False

    def need_manage(self, user_id: int) -> bool:
        if not (user_id in self.protect_bot_ids):
            return False

        if self.over_reply_time_limit(user_id):
            return True
        current_time_seconds = int(time.time())
        self.reply_time[user_id] = current_time_seconds
        log_info(f"update bot:{user_id} new time.")

        return False

    def is_at_message(self, bot_message: str) -> bool:
        return True
        # return '[CQ:at,qq=' in bot_message

    def manage_event(self, bot_id: int, bot_message: str):
        if not self.is_at_message(bot_message):
            log_dbg("no have at, no need manage")
            return ""

        if self.over_reply_time_limit(bot_id):
            current_time_seconds = int(time.time())
            if not self.reply_time[bot_id]:
                self.reply_time[bot_id] = current_time_seconds
                log_info(f"update bot:{bot_id} first time.")
                return ""
            self.reply_time[bot_id] = current_time_seconds
            log_info(f"update bot:{bot_id} new time.")
            return " 😱 ~ "

        return ""


class AppQQ:
    response_user_ids: Set[int] = {}
    response_group_ids: Set[int] = {}
    master_uid: int = 0
    port: int = 5700
    host: str = "127.0.0.1"
    type: str = "go-cqhttp"
    go_cqhttp: GoCQHTTP
    app: Any
    http_server: Any
    message: Set[dict] = []
    message_size: int = 1024
    reply_message: Set[RequestData] = []
    reply_message_size: int = 1024
    running: bool = True
    manage: BotManage = BotManage()
    init: bool = False
    type: str = GoCQHTTP.name
    onebot: GoCQHTTP
    setting: Dict = {}
    models: List[str] = [GoCQHTTP.name, Shamrock.name]

    def __init__(self):
        self.__load_setting()
        self.__init_onebot()
        self.__init_listen()

    def __init_onebot(self):
        if self.type == GoCQHTTP.name:
            self.onebot = GoCQHTTP(self.setting)
        elif self.type == Shamrock.name:
            self.onebot = Shamrock(self.setting)
        else:
            log_err(f"fail to init: {self.type}")
            return

        log_dbg(f"use type: {self.type}")

    def __message_append(self, msg):
        if len(self.message) >= self.message_size:
            log_err("msg full: {}. bypass: {}".format(str(len(self.message)), str(msg)))
            return False

        self.message.append(msg)

        return True

    def __iter__(self):
        return self

    def __next__(self):
        if not self.message:
            raise StopIteration
        else:
            return self.message.pop()

    def __reply_append(self, reply: RequestData):
        if len(self.reply_message) >= self.reply_message_size:
            log_err(
                "reply full: {}. bypass: {}".format(
                    str(len(self.reply_message)), str(reply)
                )
            )
            return False

        self.reply_message.append(reply)

        log_dbg("append new reply.")

        return True

    def reply_data(self, req: RequestData) -> bool:
        try:
            log_dbg("send get: " + str(req.url))
            response = requests.request(
                method=req.method,
                url=req.url,
                headers=req.headers,
                json=req.data,
                proxies={},
            )
            log_dbg("res code: {} data: {}".format(str(response), str(response.text)))
            if response.status_code != 200:
                log_err("code: {}. fail to reply, sleep.".format(response.status_code))
                return False
            return True
        except Exception as e:
            log_err("fail to reply, sleep: " + str(e))
            return False

    def reply(self):
        while self.running:
            if not len(self.reply_message):
                time.sleep(1)
                continue

            log_info("recv reply. try send qq server")

            for reply_req in self.reply_message:

                res = self.reply_data(reply_req)
                if not res:
                    log_err(f"fail to send reply, remove msg: {str(res)}. sleep 5s...")
                    self.reply_offline()

                self.reply_message.remove(reply_req)

    def is_message(self, msg) -> bool:
        return self.onebot.is_message(msg)

    def is_private(self, msg) -> bool:
        return self.onebot.is_private(msg)

    def is_group(self, msg) -> bool:
        return self.onebot.is_group(msg)

    def get_name(self, msg):
        return self.onebot.get_name(msg)

    def get_question(self, msg):
        return self.onebot.get_question(msg)

    def get_user_id(self, msg):
        return self.onebot.get_user_id(msg)

    def get_group_id(self, msg):
        return self.onebot.get_group_id(msg)

    def get_message(self, msg):
        return self.onebot.get_message(msg)

    def reply_private(self, user_id: int, reply: str):
        reply = self.onebot.get_reply_private(user_id, reply)
        return self.__reply_append(reply)

    def reply_group(self, group_id: int, user_id: int, reply):
        reply = self.onebot.get_reply_group(group_id, user_id, reply)
        return self.__reply_append(reply)

    def get_image_message(self, file) -> str:
        return self.onebot.get_image_cq(file)

    def reply_question(self, msg, reply):
        if not len(reply):
            log_info("reply is empty.")
            return None

        user_id = self.get_user_id(msg)

        if self.is_private(msg):
            return self.reply_private(user_id, reply)
        elif self.is_group(msg):
            group_id = self.get_group_id(msg)
            return self.reply_group(group_id, user_id, reply)

        return None

    def has_message(self):
        return len(self.message)

    def reply_permission_denied(self, msg):
        if not self.is_permission_denied(msg):
            return

        meme_com = Config.meme.common
        img_meme_com = self.get_image_message(meme_com)

        self.reply_question(msg, "非服务对象 :(")
        self.reply_question(msg, img_meme_com)

    def is_online(self) -> bool:
        qq_info_url = self.onebot.make_url_get_qq_info()
        reply = RequestData(method="GET", url=qq_info_url)

        return self.reply_data(reply)

    def reply_online(self):
        return self.reply_private(self.master_uid, "server init complate :)")

    def reply_offline(self):
        reply = self.onebot.get_reply_private(
            self.master_uid, "server unknown error :("
        )
        return self.reply_data(reply)

    # notify permission denied
    def is_permission_denied(self, msg) -> bool:
        if self.is_private(msg):
            uid = self.get_user_id(msg)
            if uid == self.master_uid:
                return False
            if uid in self.response_user_ids:
                return False

            return True

        elif self.is_group(msg):
            # only use at on group.
            message = self.get_message(msg)
            if not self.onebot.is_at_self(message):
                return False

            uid = self.get_user_id(msg)
            gid = self.get_group_id(msg)

            if uid in self.response_user_ids and gid in self.response_group_ids:
                return False

            return True

        return False

    def need_reply(self, msg) -> bool:
        if self.is_private(msg):
            uid = self.get_user_id(msg)
            if uid == self.master_uid:
                return True
            if uid in self.response_user_ids:
                return True
        elif self.is_group(msg):
            # only use at on group.
            message = self.get_message(msg)
            if not self.onebot.is_at_self(message):
                return False

            gid = self.get_group_id(msg)

            if not (gid in self.response_group_ids):
                return False

            uid = self.get_user_id(msg)

            if uid == self.master_uid:
                return True

            if uid in self.response_user_ids:
                return True

        return False

    def need_check_manage_msg(self, msg) -> bool:
        if not self.is_group(msg):
            return False

        user_id = self.get_user_id(msg)
        group_id = self.get_group_id(msg)
        protect_bot_ids = self.manage.protect_bot_ids

        if not (group_id in self.response_group_ids):
            return False

        if user_id in protect_bot_ids:
            return True

        return False

    def manage_msg(self, msg):
        group_id = self.get_group_id(msg)
        if not (group_id in self.response_group_ids):
            return

        user_id = self.get_user_id(msg)
        if not self.manage.need_manage(user_id):
            return

        message = self.get_message(msg)
        notify_msg = self.manage.manage_event(user_id, message)
        if not len(notify_msg):
            return

        self.manage.reply_cur_cnt += 1
        if self.manage.reply_cur_cnt < self.manage.reply_max_cnt:
            log_dbg(
                f"no need manage: [{self.manage.reply_cur_cnt}/{self.manage.reply_max_cnt}]"
            )
            return

        self.reply_group(group_id, self.master_uid, f" {notify_msg}")
        self.manage.reply_cur_cnt = 0

    def __init_listen(self):
        self.app = Flask(__name__)

        @self.app.route("/", methods=["POST"])
        def listen():
            if not request.is_json:
                return make_response("failed", 400)
            msg = request.get_json()
            log_dbg(f"recv: {msg}")
            if not self.is_message(msg):
                log_dbg("skip not msg.")
                return make_response("skip", 200)
            log_info("recv msg: " + str(msg))
            if self.need_reply(msg):
                log_info("need reply, append msg.")
                self.__message_append(msg)
            elif self.is_permission_denied(msg):
                log_info("user permission_denied")
                self.reply_permission_denied(msg)
            elif self.need_check_manage_msg(msg):
                log_info("need check manage msg")
                self.manage_msg(msg)
            else:
                log_info("no need reply")

            return make_response("ok", 200)

    def server(self):
        # 开启回复线程
        threading.Thread(target=self.reply).start()

        from gevent import pywsgi

        self.http_server = pywsgi.WSGIServer(
            listener=(self.host, self.port), application=self.app
        )
        self.http_server.serve_forever()

    def stop(self):
        self.running = False
        try:
            self.http_server.stop()
        except Exception as e:
            log_dbg(f"Exit raise: {e}")

    def __load_setting(self):
        setting = {}
        try:
            setting = Config.load_setting("qq")
        except Exception as e:
            log_err(f"fail to load {self.type}: {e}")
            setting = {}
            return
        self.setting = setting

        try:
            self.master_uid = setting["master_uid"]
        except Exception as e:
            log_err(f"fail to load qq: {e}")
            self.master_uid = 0

        try:
            self.response_user_ids = set(setting["response_user_ids"])
        except Exception as e:
            log_err(f"fail to load qq: {e}")
            self.response_user_ids = set()
        try:
            self.response_group_ids = set(setting["response_group_ids"])
        except Exception as e:
            log_err(f"fail to load qq: {e}")
            self.response_group_ids = set()

        try:
            self.host = setting["host"]
        except Exception as e:
            log_err(f"fail to load host: {e}")
            self.port = '0.0.0.0'
        
        try:
            port = setting["port"]
            self.port = int(port)
        except Exception as e:
            log_err(f"fail to load port: {e}")
            self.port = 5701

        try:
            self.type = setting["type"]
        except Exception as e:
            log_err(f"fail to load port: {e}")
            self.type = self.models[0]

        if self.type not in self.models:
            raise Exception(f"no support type: {self.type}, please use: {self.models}")
