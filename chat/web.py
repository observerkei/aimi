from flask import Flask, request, render_template, Response
import json
import threading
import time
from typing import Any

from tool.util import log_info, log_err, log_dbg
from tool.aimi_plugin import aimi_plugin


openai_stream_response = [
    {
      "choices": [
        {
          "delta": {
            "role": "assistant"
          },
          "finish_reason": None,
          "index": 0
        }
      ],
      "created": 1677825464,
      "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
      "model": "gpt-3.5-turbo-0301",
      "object": "chat.completion.chunk"
    },
    {
      "choices": [
        {
          "delta": {
            "content": "Master "
          },
          "finish_reason": None,
          "index": 1
        }
      ],
      "created": 1677825464,
      "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
      "model": "gpt-3.5-turbo-0301",
      "object": "chat.completion.chunk"
    },
    {
      "choices": [
        {
          "delta": {
            "content": "~ "
          },
          "finish_reason": None,
          "index": 2
        }
      ],
      "created": 1677825464,
      "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
      "model": "gpt-3.5-turbo-0301",
      "object": "chat.completion.chunk"
    },
    {
      "choices": [
        {
          "delta": {},
          "finish_reason": "stop",
          "index": 3
        }
      ],
      "created": 1677825464,
      "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
      "model": "gpt-3.5-turbo-0301",
      "object": "chat.completion.chunk"
    }
]

class AimiWebApi:
    api_host: str = '127.0.0.1'
    api_port: int = 4642
    app: Any
    http_server: Any

    def __init__(self):
        self.__listen_init()
        log_dbg('web init done')

    def __make_stream_reply(self, reply: str) -> str:
        stream = {
          "choices": [
            {
              "delta": {
                "content": str(reply),
              },
              "finish_reason": None,
              "index": 2
            }
          ],
          "created": 1677825464,
          "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
          "model": "gpt-3.5-turbo-0301",
          "object": "chat.completion.chunk"
        }
        return 'event: message\ndata:' + json.dumps(stream) + "\n\n"
        
    def __listen_init(self):
    
        self.app = Flask(__name__)
        
        @self.app.route('/api', methods=['POST'])
        def handle_post_api_request():
        
            def event_stream(question: str):
                if not len(question):
                    yield self.__make_stream_reply('question is empty.')
                    yield 'event: end\ndata: [DONE]\n\n'
                    return

                prev_text = ''
                for answer in aimi_plugin.bot_ask('poe', question):
                    message = answer["message"][len(prev_text) :]
                    yield self.__make_stream_reply(message)
                    prev_text = answer["message"]

                yield 'event: end\ndata: [DONE]\n\n'
            
            url = request.url
            body = request.get_data().decode('utf-8')
            log_dbg(f"Received a api request: URL={url}, body={body}")

            question = ''
            try:
                # 将json字符串转化为json数据
                web_request = json.loads(body)

                # 获取message数组的最后一条数据
                last_message = web_request["messages"][-1]
                question = last_message['content']
                log_dbg(f'get question: {question}')
            except Exception as e:
                log_err(f'fail to get requestion: {e}')
                
            # 返回该响应
            return Response(event_stream(question), mimetype='text/event-stream')

    def server(self):
        from gevent import pywsgi
        self.http_server = pywsgi.WSGIServer(
            listener = (self.api_host, self.api_port),
            application = self.app,
            log = None 
        )
        
        log_info('web start')
        
        self.http_server.serve_forever()

chat_web = AimiWebApi()
