# aimi

# function

1. catgirl
2. Chat AI developed based on OpenAI/bard/bing/plugin
3. Support qq individual or group chat permission
4. mathematical expression(LaTex) / html converted to pictures

# environmental requirement

1. python version >= 3.9
2. go-cqhttp bin download on https://github.com/Mrs4s/go-cqhttp/releases
3. go-cqhttp link/put on ./run/
4. An OpenAI account for your own use.

If you want to use text-to-image, you'll need to add these

1. pandoc
2. wkhtmltopdf

# running

1. run go-cqhttp.

  1.1. open go-cqhttp http proxy mode

set go-cqhttp config.yml:
```yaml
server:
  - http:
      host: # you go-cqhttp listen host, eg: 127.0.0.1
      port: # you go-cqhttp listen port, eg: 5700
      post:
        - url: # you go-cqhttp post chat to chat/qq.py: listent http://host:port, eg: 'http://127.0.0.1:5701' 
```

  1.2 run go-cqhttp, Please make sure that he can receive qq messages. You need to solve login and authentication issues, see the official user feedback for details.

```bash
cd run && ./go-cqhttp -faststart > go-cqhttp.log
```

2. set you reply qq and group on ./run/setting.yml

```yaml
qq:
  master_id: # admin user qq id, eg: 123
  response_user_ids:
    - # reply user qq id list, eg: 123
  response_group_ids:
    - # reply group id list, eg: 321
```

4. Visit this link to get your OpenAI access_token:

(For development communication only)

https://chat.openai.com/api/auth/session

save to ./run/setting.yml

```yaml
openai_config:
  access_token: # your access_token

```

5. if you use python3.9, then use:

  5.1 install dependent package

```bash
pip3.9 install -r ./run/requirements.txt
```

If you want to use mathematical expression(LaTex) / html to turn images and you are a class ubuntu system

```bash
apt install -y pandoc wkhtmltopdf
```

  5.2 run aimi

```bash
cd ./ && python3.9 main.py > ./run/aimi.log
```

If you set up correctly, then you can see qq messages, as well as the administrator qq see aimi online.

Have a good time!

6. express gratitude

https://github.com/acheong08/ChatGPT

https://github.com/Mrs4s/go-cqhttp

https://github.com/LSTM-Kirigaya/go-cqhttp-python-server

https://github.com/vercel/examples

7. release claims

Development and communication are welcome, final interpretation and copyright are reserved, based on the MIT agreement.
