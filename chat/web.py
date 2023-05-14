from flask import Flask, request, render_template, Response
import json
import threading
import time

app = Flask(__name__)

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

@app.route('/api', methods=['POST'])
def handle_post_api_request():
    def event_stream():
        for stream in openai_stream_response:
            res = 'event: message\ndata:' + json.dumps(stream) + "\n\n"
            yield res
            time.sleep(0.3)

        yield 'event: end\ndata: [DONE]\n\n'
    
    url = request.url
    body = request.get_data().decode('utf-8')
    print(f"Received a api request: URL={url}, body={body}")

    # 获取 POST 请求的数据
    data = request.get_json()

    # 返回该响应
    return Response(event_stream(), mimetype='text/event-stream')

def run_app():
    app.run(port=2464)

if __name__ == '__main__':
    t = threading.Thread(target=run_app)
    t.start()

    while True:
        # do something here to receive and process incoming requests
        with app.test_request_context('/'):
            url = request.url
            body = request.get_data().decode('utf-8')
            log_text = f"Received a request: URL={url}, body={body}\n"
            # do something with log_text
            time.sleep(1)
            print(log_text)
            
