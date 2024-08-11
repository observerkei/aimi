# aimi

# function

1. catgirl
2. Chat AI developed based on OpenAI/gemini/bing/plugin
3. Support qq individual or group chat permission
4. mathematical expression(LaTex) / html converted to pictures
5. Extension of robots via plugins is supported
6. Translation and execution of Functions from Natural Language to programming Language

# environmental requirement

1. Python version >= 3.9
2. Get a OneBot server ready, like Shamrock on https://yuyue-amatsuki.github.io/OpenShamrock
3. cp ./run/setting.yml.example ./run/setting.yml
4. An OpenAI account for your own use.

If you want to use text-to-image, you'll need to add these

1. pandoc
2. wkhtmltopdf

# running

## configuring dependencies


1. install dependent package, if you use python3.9, then use:

```bash
pip3.9 install -r ./run/requirements.txt
```

or use:  

```bash
cd run && bash -x build_environment.sh
```

If you want to use mathematical expression(LaTex) / html to turn images and you are a class ubuntu system

```bash
apt install -y pandoc wkhtmltopdf
```


### running as web


1. Make sure you have nodejs installed

```bash
apt-get install nodejs
```

2. Installing web dependencies

```bash
cd ./app/app_web/
npm i
```

3. Starting the Web server. When the web server has started successfully, open a url like http://localhost:2300 to view the front-end page, depending on the port on which the logs were run

```bash
npm run dev
```

4. run bot

```bash
cd ./ && python3.9 main.py > ./run/aimi.log
```

5. Fill in the api-key for chatgpt's api in the web page, Start a chat.


### running as a OneBot QQ server 

1. run Shamrock, go-cqhttp or another OneBot server

set setting:

```yaml
qq:
  type: go-cqhttp
  port: '5701' # Local listening port
  post_host: 'localhost' # IP/domain of the QQ message parsing HTTP server
  post_port: '5700' # Port of the QQ message parsing server
  uid: 123 # QQ number used for logging into the QQ message parsing server, which is the bot's own QQ number.
  master_uid: 1234 # Administrator's QQ number
  response_user_ids: # List of QQ numbers that the bot can reply to
    - 1234
  response_group_ids: # List of group IDs that the bot can reply to
    - 123456789
  manage: 
    reply_time_limit_s: 3600 # Time interval limit for each message
    protect_bot_ids: # List of users who need speech restrictions (requires administrator permissions)
      -  12345678
```

2. run OneBot server, Please make sure that he can receive qq messages. You need to solve login and authentication issues, see the official user feedback for details.


3. run bot

```bash
cd ./ && python3.9 main.py > ./run/aimi.log
```


If you set up correctly, then you can see qq messages, as well as the administrator qq see aimi online.

Have a good time!



> How to get your OpenAI access token:

(For development communication only)

https://chat.openai.com/api/auth/session

save to ./run/setting.yml

```yaml
openai:
  access_token: # your access_token
```

6. express gratitude

https://github.com/acheong08/ChatGPT

https://github.com/Mrs4s/go-cqhttp

https://github.com/LSTM-Kirigaya/go-cqhttp-python-server

https://github.com/vercel/examples

https://github.com/mckaywrigley/chatbot-ui

https://yuyue-amatsuki.github.io/OpenShamrock/

7. release claims

Development and communication are welcome, final interpretation and copyright are reserved, based on the MIT agreement.
