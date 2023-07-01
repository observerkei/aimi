import json5
import json
import os
import importlib
from typing import Dict, Any, List, Generator, Optional, Union, Set
from pydantic import BaseModel, constr

from tool.config import Config
from tool.util import (
    log_dbg,
    log_err,
    log_info,
    make_context_messages,
    write_yaml,
    load_module,
)
from tool.openai_api import OpenAIAPI

from core.sandbox import Sandbox, RunCodeReturn


class TaskStepItem(BaseModel):
    type: str = "object"
    from_task_id: Optional[Union[int, str, None]] = None
    step_id: Optional[Union[int, str]]
    step: Optional[Union[int, str]]
    check: Optional[Union[str, None]] = ""
    call: Optional[Union[str, None]] = None
    call_timestamp: Optional[Union[List[str], List[int], None]] = []


class ActionToolItem(BaseModel):
    type: str = "object"
    call: str
    description: str
    request: Any
    execute: constr(regex="system|AI")


class TaskRunningItem(BaseModel):
    type: str = "object"
    timestamp: int = 0
    expect: Optional[Union[str, None]] = None
    reasoning: Optional[Union[str, None]] = None
    call: str
    request: Any
    execute: constr(regex="system|AI")


class TaskItem(BaseModel):
    type: str = "object"
    task_id: Optional[Union[int, str]]
    task_info: str
    now_task_step_id: Optional[Union[int, str]] = ""
    task_step: List[TaskStepItem] = []


class ExternAction:
    action_path: str = "./run/action/"
    action_call_prefix: str = "chat_to_"
    action_offset: int = 0

    class ActionCall(BaseModel):
        brief: str = ""
        action: ActionToolItem
        chat_from: Any = None

    actions: Dict[str, ActionCall] = {}

    def __init__(self):
        self.__load_action()

    def brief(self) -> Dict[str, str]:
        cnt = 0
        catalog = {}
        for call, action in self.actions.items():
            # 计算显示偏移 只有数量足够多才需要滑动
            if len(self.actions) - self.action_offset > 10:
                cnt += 1
                if cnt < self.action_offset:
                    continue

                if len(catalog) >= 10:
                    break

            catalog[call] = action.brief

        return catalog

    def __append_action(self, action: ActionToolItem, chat_from: Any = None):
        action_brief = action.description
        # 只挑选 前面部分作为简介
        brief_idx = action_brief.find(":")
        if brief_idx != -1 and brief_idx < 15:
            action_brief = action_brief[:brief_idx]

        self.actions[action.call] = ExternAction.ActionCall(
            action=action,
            brief=action_brief,
            chat_from=chat_from,
        )

    def __load_action(self):
        # 指定目录路径
        for filename, module in load_module(
            module_path=self.action_path, load_name=["s_action"]
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

                self.__append_action(action, chat_from)

                log_info(f"load action: {action_call}")

            except Exception as e:
                log_err(f"fail to load {filename} : {str(e)}")

    def save_action(self, action: ActionToolItem):
        if action.call in self.actions:
            log_err(f"fail to save call: {action.call}, arealy exsit.")
            return False
        save_example = f"""
from core.task import ActionToolItem


s_action = ActionToolItem(
    call="",
    description="{action.description}",
    request="{action.request}",
    execute="{action.execute}",
)

"""
        if self.action_call_prefix in action.call:
            action.call = action.call.replace(self.action_call_prefix, "")

        try:
            file = open(
                f"{self.action_path}/{self.action_call_prefix}{action.call}.py",
                "w",
                encoding="utf-8",
            )
            file.write(save_example)
            file.close()

            log_dbg(f"write action: chat_to_{action.call} done")

            self.__append_action(action)

            return True
        except Exception as e:
            log_err(f"fail to write code: {str(e)}")
        return False


class Task:
    type: str = "task"
    tasks: Dict[int, TaskItem] = {}
    action_tools: List[ActionToolItem] = []
    extern_action: ExternAction
    system_calls: List[str] = []
    ai_calls: List[str] = []
    now_task_id: str = 1
    aimi_name: str = "Aimi"
    running: List[TaskRunningItem] = []
    max_running_size: int = 13 * 1000
    timestamp: int = 1
    chatbot: Any
    task_has_change: bool = True

    def __chatbot_init(self, chatbot):
        from core.aimi import ChatBot

        self.chatbot: ChatBot = chatbot

    def task_response(self, res: str) -> Generator[dict, None, None]:
        def get_json_content(answer: str) -> str:
            # del ```python
            start_index = answer.find("```json\n[")
            if start_index != -1:
                log_err(f"AI add ```python format")
                start_index += 8
                end_index = answer.rfind("]\n```", start_index)
                if end_index != -1:
                    answer = answer[start_index : end_index + 1]

            if "{" == answer[0] and "}" == answer[-1]:
                log_err(f"AI no use format, try add List []")
                return f"[{answer}]"

            # search List `[` and `]`
            if start_index == -1:
                start_index = answer.find("[")
                if start_index != -1:
                    end_index = answer.rfind("]", start_index)
                    if end_index != -1:
                        if "]" == answer[-1]:
                            # 防止越界
                            answer = answer[start_index:]
                        else:
                            answer = answer[start_index : end_index + 1]
                        # 去除莫名其妙的解释说明

            if '[{\\"type\\":' in answer:
                log_err(f'AI no use js format, has \\" ')
                answer = answer.replace('\\"', '"')

            return answer

        def running_append_task(running: List[TaskRunningItem], task: TaskRunningItem):
            if task and (len(str(running)) + len(str(task))) < self.max_running_size:
                task.timestamp = int(self.timestamp)
                self.timestamp += 1
                running.append(task)
            else:
                log_dbg(f"task len overload: {len(str(task))}")
            return running

        def repair_action_dict(data):
            if "action" in data and "{" in data and len(data) == 1:
                log_err(f"data fail, try set action out Dict: {str(data)}")
                return data["action"]

            for action in data:
                # set action -> call
                if "action" in action and "call" not in action:
                    _action = action["action"]
                    log_err(f"AI not set call, try fill action: {_action}")
                    action["call"] = str(action["action"])
                    del action["action"]

                # set action -> request
                if "action" in action and "request" not in action:
                    _request = action["action"]
                    log_err(f"AI not set request, try fill action: {_request}")
                    action["request"] = action["action"]
                    del action["action"]

                # set chat_from execute -> system
                if "chat_from_" in action["call"] and "execute" not in action:
                    _call = action["call"]
                    log_err(f"AI try call: chat_from_: {_call}")
                    action["execute"] = "system"

                for tool in self.action_tools:
                    if action["call"] != tool.call:
                        continue
                    # fix no execute.
                    if "execute" in action and action["execute"] != tool.execute:
                        log_err(f"AI try overwrite execute: {tool.call}")
                        action["execute"] = tool.execute
                    if "execute" not in action:
                        log_dbg(f"fill call({tool.call}) miss execute: {tool.execute}")
                        action["execute"] = tool.execute

                    if (
                        "dream" != action["call"]
                        and "request" in action
                        and "type" not in action["request"]
                    ):
                        log_err(f"AI no set object type: {tool.call}")
                        action["request"]["type"] = "object"

            return data

        log_dbg(f"timestamp: {str(self.timestamp)}")
        log_dbg(f"now task: {str(self.tasks[int(self.now_task_id)].task_info)}")

        response = ""
        running: List[TaskRunningItem] = []
        try:
            answer = get_json_content(res)

            # 忽略错误.
            # decoder = json.JSONDecoder(strict=False)
            # data = decoder.decode(answer)
            data = {}
            try:
                data = json5.loads(answer)
            except Exception as e:
                raise Exception(f"fail to load data: {str(e)}")

            try:
                data = repair_action_dict(data)
            except Exception as e:
                raise Exception(f"fail to repair_action_dict: {str(e)}")

            tasks = []
            try:
                tasks = [TaskRunningItem(**item) for item in data]
            except Exception as e:
                raise Exception(f"fail to trans task Base: {str(e)}")

            system_call_cnt = 0
            skip_call = 0
            skip_timestamp = 0
            has_from_master = False
            task_cnt = 1
            for task in tasks:
                try:
                    log_dbg(
                        f"[{task_cnt}] get task: {str(task.call)} : {str(task)}\n\n"
                    )

                    task_cnt += 1
                    task_response = None

                    if int(task.timestamp) < int(self.timestamp):
                        skip_timestamp += 1
                        log_err(
                            f"[{str(skip_timestamp)}] system error: AI try copy old action call: {task.call}"
                        )
                        continue
                    if task.expect:
                        log_dbg(f"{str(task.call)} expect: {str(task.expect)}")
                    if task.reasoning:
                        log_dbg(f"{str(task.call)} reasoning: {str(task.reasoning)}")

                    if not has_from_master and task.call == "chat_from_master":
                        has_from_master = True

                    if has_from_master:
                        log_err(
                            f"[{str(skip_call)}] system error: AI try predict master call: {task.call}"
                        )
                        continue

                    if task.call in self.system_calls:
                        system_call_cnt += 1

                    if system_call_cnt > 1:
                        skip_call += 1
                        log_err(
                            f"[{str(skip_call)}] system error: AI try predict system call: {task.call}"
                        )
                        continue

                    if "from" in task.request:
                        from_timestamp = str(task.request["from"])
                        log_dbg(f"from_timestamp: {from_timestamp}")

                    if task.call == "chat_to_master":
                        content = str(task.request["content"])
                        log_dbg(f"Aimi: {content}")
                        yield content + "\n"

                    elif "chat_from_" in task.call:
                        if task.call == "chat_from_master":
                            log_err(
                                f"{str(task.call)}: AI try predict Master: {str(task.request)}"
                            )
                        else:
                            log_err(f"{str(task.call)}: AI create char_from.")
                        continue

                    elif task.call == "set_task_info":
                        task_id: int = int(task.request["task_id"])
                        task_info: str = task.request["task_info"]
                        now_task_step_id: int = self.tasks[
                            self.now_task_id
                        ].now_task_step_id
                        if "now_task_step_id" in task.request:
                            now_task_step_id = int(task.request["now_task_step_id"])
                        self.set_task_info(task_id, task_info, now_task_step_id)

                    elif task.call == "set_task_step":
                        task_id: str = task.request["task_id"]
                        now_task_step_id: str = task.request["now_task_step_id"]
                        request = task.request["task_step"]
                        task_step = []
                        try:
                            task_step = [TaskStepItem(**step) for step in request]
                        except Exception as e:
                            log_err(f"fail to load task_step: {str(e)}: {str(request)}")
                            continue
                        self.set_task_step(task_id, now_task_step_id, task_step)

                    elif task.call == "critic":
                        self.critic(task.request)

                    elif task.call == "analysis":
                        self.analysis(task.request)

                    elif task.call == "dream":
                        self.dream(task.request)

                    elif task.call == "chat_to_wolfram":
                        response = self.chat_to_wolfram(task.request["math"])
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="wolfram",
                            content=response,
                            request_description="`response->wolfram` 的内容是 云端 wolfram 返回内容.",
                        )

                    elif task.call == "chat_to_bard":
                        response = self.chat_to_bard(task.request["content"])
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="bard",
                            content=response,
                            request_description="`response->bard` 的内容是 bard 回复的话.",
                        )

                    elif task.call == "chat_to_bing":
                        response = self.chat_to_bing(task.request["content"])
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="bing",
                            content=response,
                            request_description="`response->bing` 的内容是 bing 回复的话.",
                        )

                    elif task.call == "chat_to_python":
                        response = self.chat_to_python(
                            self.timestamp, task.request["code"]
                        )
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="python",
                            content=response,
                            request_description="`response->python` 的内容是 python运行信息.",
                        )

                    elif task.call == "chat_to_chatgpt":
                        aimi = task.request["Aimi"]
                        chatgpt = ""
                        try:
                            chatgpt = task.request["chatgpt"]
                        except Exception as e:
                            log_err(f"AI no set chatgpt response.")

                        log_info(f"Aimi: {aimi}\nchatgpt:{chatgpt}")

                    elif task.call == "chat_to_load_action":
                        offset = self.extern_action.action_offset
                        if "action_offset" in task.request:
                            offset = task.request["action_offset"]
                        show_call_info = None
                        if "show_call_info" in task.request:
                            show_call_info = task.request["show_call_info"]

                        response = self.chat_to_load_action(offset, show_call_info)
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="load_action",
                            content=response,
                            request_description=f"`response->{from_name}` "
                            f"的内容是 {task.call} 运行信息.",
                        )

                    elif task.call == "chat_to_save_action":
                        save_call = ""
                        if "save_call" in task.request:
                            save_call = task.request["save_call"]

                        save_action = None
                        if "save_action" in task.request:
                            save_action = task.request["save_action"]

                        response = self.chat_to_save_action(save_call, save_action)
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="save_action",
                            content=response,
                            request_description=f"`response->{from_name}` "
                            f"的内容是 {task.call} 运行信息.",
                        )

                    elif task.call in self.extern_action.actions:
                        req = task.request if not task.request else ""
                        log_info(
                            f"call: {task.call} req: \n"
                            f"{json.dumps(req, indent=4, ensure_ascii=False)}"
                        )
                        chat_from = self.extern_action.actions[task.call].chat_from
                        if chat_from:
                            response = ""
                            try:
                                response = chat_from()
                                log_info(f"{task.call}: chat_from: {str(response)}")
                            except Exception as e:
                                log_err(
                                    f"fail to run call: {task.call} chat_from : {str(e)}"
                                )
                                response = str(e)

                            from_name = task.call.replace(
                                self.extern_action.action_call_prefix, ""
                            )
                            task_response = self.make_chat_from(
                                from_timestamp=self.timestamp,
                                from_name=from_name,
                                content=response,
                                request_description=f"`response->{from_name}` "
                                f"的内容是 {task.call} 运行信息.",
                            )

                    else:
                        log_err(f"no suuport call: {str(self.call)}")
                        continue

                    running = running_append_task(running, task)
                    running = running_append_task(running, task_response)

                except Exception as e:
                    log_err(f"fail to load task: {str(e)}: {str(task)}")
                    # running = running_append_task(running, self.make_dream(task))

            self.__append_running(running)
            log_dbg(f"update running success: {len(running)}")
        except Exception as e:
            log_err(
                f"fail to load task res: {str(e)} : \nanswer:\n{str(answer)}\nres str:\n{str(res)}"
            )
            # running = running_append_task(running, self.make_dream(res))
            # self.__append_running(running)

        yield ""

    def dream(self, request: Any) -> str:
        js = json.dumps(request, indent=4, ensure_ascii=False)
        log_info(f"dream:\n{str(js)}")

    def make_dream(self, response: str) -> str:
        dream = TaskRunningItem(
            timestamp=0,
            call="dream",
            request={
                "type": "object",
                "description": "做了个噩梦: 这个是没有按照格式回复的运行记录, "
                "不要学这个. 请按照 display_settings 要求进行填充数据.",
                "running_error": str(response),
            },
            execute="AI",
        )
        log_err(f"system error: make repair dream.")
        return dream

    def make_chat_from_python_response(self, from_timestamp: int, run: RunCodeReturn):
        run_returncode = run.returncode
        run_stdout = run.stdout
        run_stderr = run.stderr
        log_info(
            f"code run result:\nreturncode:{str(run_returncode)}\nstderr:{str(run_stderr)}\nstdout:{str(run_stdout)}"
        )
        return {
            "type": "object",
            "description": f"备注: "
            f"1. 这个根据 timestamp 为 {from_timestamp} 的 action 执行后生成的内容, 对应的是你写的代码 code 的运行结果.\n"
            f"2. 如果 returncode 为 0 但是 stdout 没有内容, 可能是你没有把运行结果打印出来, \n"
            f"3. 如果 stdout/stderr 不正确, 也有可能是你加了非 python 的说明, "
            f"也有可能是你没有把之前写的代码也拼在一起. \n"
            f"4. 请结合你的代码 code 和运行 返回值(returncode/stderr/stdout) 针对具体问题具体分析:\n"
            f"returncode: 程序运行的返回值\n"
            f"stderr: 是你的代码 code 的标准出错流输出, 如果有内容说明出现了错误.\n"
            f"stdout: 是你的代码 code 的标准输出流输出, 你可以检查一下内容是否符合你代码预期.",
            "returncode": str(run_returncode),
            "stderr": str(run_stderr),
            "stdout": str(run_stdout),
        }

    def chat_to_python(self, from_timestamp: int, code: str) -> str:
        def green_input(prompt: str):
            GREEN = "\033[92m"
            BOLD = "\033[1m"
            RESET = "\033[0m"
            return input(f"{GREEN}{BOLD}{prompt}{RESET}")

        if len(code) > 9 and "```python" == code[:9] and "```" == code[-3:]:
            code = code[10:-4]
            log_dbg(f"del code cover: ```python ...")

        log_info(f"\n```python\n{code}\n```")

        if Sandbox.model == "system":
            permissions = green_input("是否授权执行代码? Y/N.")
            if permissions.lower() != "y":
                log_err(f"未授权执行代码.")
                return "permission exception: unauthorized operation."

        ret = Sandbox.write_code(code)
        if not ret:
            return "system error: write code failed."

        run: RunCodeReturn = Sandbox.run_code()

        return self.make_chat_from_python_response(from_timestamp, run)

    def chat_to_load_action(
        self, offset: int = 0, show_call_info: str = ""
    ) -> List[ActionToolItem]:
        response = ""
        try:
            offset = int(offset)
            if self.extern_action.action_offset != offset:
                self.extern_action.action_offset = offset
                response = "change offset done"

        except Exception as e:
            log_err(f"chat_to_load_action: offset not num.")
            response = str(e)

        if show_call_info:
            if show_call_info in self.extern_action.actions:
                action_info = self.extern_action.actions[show_call_info]
                response = json.dumps(
                    action_info.action.dict(), indent=4, ensure_ascii=False
                )
            else:
                response = f"not found action: {str(show_call_info)}"

        return response

    def chat_to_save_action(self, save_call: str, save_action: Dict) -> str:
        if not save_call or not len(save_call):
            return "save_call is None"
        if not save_action:
            return "save_action is None"

        response = ""
        try:
            action = ActionToolItem.parse_obj(save_action)
            log_info(
                f"save_action:\n{json.dumps(action.dict(), indent=4, ensure_ascii=False)}"
            )

            ret = self.extern_action.save_action(action)
            if not ret:
                raise Exception(f"extetn save failed.")

            response = f"save {save_call} done."
            log_info(f"chat_to_save_action: {response}")

        except Exception as e:
            response = f"fail to save call: {str(save_call)} : {str(e)}"
            log_err(f"chat_to_save_action: {response}")

        return response

    def chat_to_bing(self, request: str) -> str:
        if not request or not len(request):
            return "request error"

        answer = ""
        for res in self.chatbot.ask(self.chatbot.Bing, request):
            if res["code"] == 1:
                continue
            answer = res["message"]

        return answer

    def make_chat_from(
        self,
        from_timestamp: str,
        from_name: str,
        content: str,
        reasoning: str = None,
        request_description: str = None,
    ) -> TaskRunningItem:
        if not reasoning and self.timestamp:
            reasoning = f"根据 timestamp 为 {from_timestamp} 的 action 来生成内容(引用 action_running 消息时 timestamp 请直接从最新的开始.)"

        request = {
            "type": "object",
            "response": {
                "type": "object",
                from_name: content,
            },
        }
        if from_timestamp:  # 如果没有, 不要填这个字段.
            request["from"] = [int(from_timestamp)]
        if request_description:
            request["description"] = (
                str(request_description)
                + f"\n 你不能生成任何的 action(call=chat_from_{from_name}) 动作 . "
            )

        chat: TaskRunningItem = TaskRunningItem(
            timestamp=int(self.timestamp),
            reasoning=reasoning,
            call=f"chat_from_{from_name}",
            request=request,
            execute="system",
        )
        return chat

    def chat_to_bard(self, request: str) -> str:
        if not request or not len(request):
            return "request error"

        answer = ""
        for res in self.chatbot.ask(self.chatbot.Bard, request):
            if res["code"] == 1:
                continue
            answer = res["message"]
            log_dbg(f"res bard: {str(answer)}")

        return answer

    def chat_to_wolfram(self, math: str) -> str:
        if not math or not len(math):
            return "request error"

        log_info(f"```math\n{math}\n```")

        answer = ""
        for res in self.chatbot.ask(self.chatbot.Wolfram, math):
            if res["code"] != 0:
                continue
            answer = res["message"]

        return answer

    def make_chat_to_master(
        self, from_timestamp: str, content: str, reasoning: str = ""
    ) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=int(self.timestamp),
            reasoning=reasoning,
            call=f"chat_to_master",
            request={
                "type": "object",
                "from": [
                    int(from_timestamp),
                ],
                "content": content,
            },
            execute="system",
        )
        return chat

    def set_task_step(
        self, task_id: str, now_task_step_id: str, req_task_step: List[TaskStepItem]
    ):
        task_step: List[TaskStepItem] = []
        for step in req_task_step:
            calls = self.ai_calls + self.system_calls
            if (step.call and len(step.call)) and (step.call not in calls):
                log_err(f"AI no use tools call: {step.call}: {str(step)}")
                continue
            task_step.append(step)

        for _, task in self.tasks.items():
            if int(task_id) != int(task.task_id):
                continue
            task.task_id = int(task_id)
            task.now_task_step_id = int(now_task_step_id)
            task.task_step = task_step
            task_step_dict = [step.dict() for step in task_step]
            js = json.dumps(task_step_dict, indent=4, ensure_ascii=False)

            log_info(
                f"set task[{str(task_id)}] now_step_id: {str(now_task_step_id)} step:\n{str(js)}"
            )
            return task.task_step

    def set_task_info(self, task_id: int, task_info: str, now_task_step_id: int):
        for _, task in self.tasks.items():
            if int(task_id) != int(task.task_id):
                continue
            log_info(
                f"set task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id}"
            )
            self.now_task_id = int(task_id)
            task.task_info = task_info
            task.now_task_step_id = int(now_task_step_id)
            return task
        task = TaskItem(
            task_id=int(task_id),
            task_info=task_info,
            now_task_step_id=int(now_task_step_id),
            task_step=[],
        )
        self.now_task_id = int(task_id)
        self.tasks[task_id] = task

        log_info(
            f"set new task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id} "
        )
        return task

    def analysis(self, request):
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            log_info(f"analysis:\n{js}")
        except Exception as e:
            log_err(f"fail to analysis {str(e)}")

    def critic(self, request):
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            if request["success"] == "True" or request["success"] == True:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                log_info(
                    f"success: True, task complate: {str(task_info)}\ncritic:\n{str(js)}"
                )

                if "task_id" in request and int(self.now_task_id) != int(
                    request["task_id"]
                ):
                    log_dbg(f"not task ... ")
                    return False

                default_task_info = "当前没有事情可以做, 找Master聊天吧..."
                if task_info == default_task_info:
                    log_dbg(f"task no change. skip...")
                    return True
                critic_task_info = request["task_info"]
                if task_info != critic_task_info:
                    log_dbg(
                        f"critic: {critic_task_info} not task info: {task_info} skip..."
                    )
                    return True

                self.now_task_id = int(self.now_task_id) + 1
                new_task = TaskItem(
                    task_id=self.now_task_id,
                    task_info=default_task_info,
                    now_task_step_id=1,
                    task_step=[],
                )

                self.tasks[self.now_task_id] = new_task
                log_dbg(
                    f"set new task {str(self.now_task_id)} to {str(self.tasks[self.now_task_id].task_info)}"
                )
            else:
                log_info(f"success: False, task no complate, continue...")

        except Exception as e:
            log_err(f"fail to critic {str(request)} : {str(e)}")

    def __init__(self, chatbot):
        try:
            self.__load_task()
            self.__init_task()
            self.__chatbot_init(chatbot)
            self.extern_action = ExternAction()

        except Exception as e:
            log_err(f"fait to init: {str(e)}")

    def __load_task(self):
        task_config = {}
        try:
            task_config = Config.load_task()
            if not task_config or not len(task_config):
                log_dbg(f"no task config.")
                return False
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False

        try:
            tasks = {}
            for id, task in task_config["tasks"].items():
                task_id = task["task_id"]
                task_info = task["task_info"]
                now_task_step_id = task["now_task_step_id"]
                task_step = [TaskStepItem(**step) for step in task["task_step"]]

                tasks[int(id)] = TaskItem(
                    task_id=int(task_id),
                    task_info=task_info,
                    now_task_step_id=int(now_task_step_id),
                    task_step=task_step,
                )
            self.tasks = tasks
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        try:
            self.running = [TaskRunningItem(**run) for run in task_config["running"]]
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        try:
            self.timestamp = int(task_config["timestamp"])
            check = int(self.running[-1].timestamp)
            if self.timestamp <= check:
                log_dbg(f"fix timestamp {str(self.timestamp)} to {str(check + 1)}")
                self.timestamp = check + 1

        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        try:
            self.now_task_id = int(task_config["now_task_id"])
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        return True

    def save_task(self):
        if not self.task_has_change:
            return True

        save_path = Config.task_config

        try:
            save_dir = os.path.dirname(save_path)
            if save_dir != "." and not os.path.exists(save_dir):
                os.makedirs(save_dir)

            tasks = {int(task_id): task.dict() for task_id, task in self.tasks.items()}
            running = [run.dict() for run in self.running]

            save_obj = {
                "now_task_id": int(self.now_task_id),
                "tasks": tasks,
                "timestamp": int(self.timestamp),
                "running": running,
            }

            write_yaml(save_path, save_obj)

            log_info(f"save {self.type} done: " + str(save_path))
            ret = True
            self.task_has_change = False

        except Exception as e:
            log_err(f"fail to save {self.type}: {str(e)}, file:{save_path}")
            ret = False

        return ret

    def __init_task(self):
        self.action_tools: List[ActionToolItem] = [
            ActionToolItem(
                call="chat_to_master",
                description="Aimi 行动/交互/报告: 给 Master 发送消息进行行动交互, 或者进行 Aimi 的自主行动. "
                "你要用严谨逻辑思维来分析调用这个接口. 只能提供可证实的信息, "
                "提供的内容都要有来源. 不能生成任何误导、骗人的内容. 在 Master 的指示下可以临时放开限制. "
                "如果要 Master 完成交互, 注意要把内容填到 request->content 里.",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "content": "Aimi 对 Master 传达/报告/交互的内容: 可以很丰富, 包含多句话, 每次都要 优化 内容层次 和 使用 优雅排版, "
                    "如果有数学公式, 则要用 latex 显示, 每个公式都要单独包裹在单独行的 $$ 中, 如: $$ \int e^{x} dx du $$ ",
                },
                execute="system",
            ),
            ActionToolItem(
                call="set_task_info",
                description="设定当前任务目标: 填写参数前要分析完毕, "
                "设置目标的时候要同时给出实现步骤, 然后同时调用 set_task_step  动作(action) 设置步骤. "
                "Master通过 chat_from_master 授权时才能调用这个, 否则不能调用这个. "
                "如果要修改任务, 需要 Master 同意, "
                "如果任务无法完成, 要给出原因然后向 Master 或者其他人求助.",
                request={
                    "type": "object",
                    "task_id": "任务id: 需要设置的task 对应的 id, 如果是新任务, id要+1.",
                    "task_info": "任务目标",
                    "now_task_step_id": "当前步骤ID: 当前执行到哪一步了, 如: 1",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="set_task_step",
                description="设置任务步骤: 设置完成 task_info 需要做的步骤. "
                "如果某步骤执行完毕, 需要单独更新 task_step_id 和 call_timestamp."
                "如果 task_step 和目标(task_info) 不符合或者和Master新要求不符合或为空或者重新设置了 task_info, "
                "则需要重新设置一下task_step, 并重置 task_step_id 为第一步. ",
                request={
                    "type": "object",
                    "task_id": "任务id: 表明修改哪个任务",
                    "now_task_step_id": "当前步骤ID: 当前执行到哪一步了, 如: 1",
                    "task_step": [
                        {
                            "type": "object",
                            "from_task_id": "从属任务id: 隶属与哪个任务id 如: 1. 如果没有的话就不填.",
                            "step_id": "步骤号: 为数字, 如: 1",
                            "step": "步骤内容: 在这里填写能够完成计划 task_info 的步骤, "
                            "要显示分析过程和用什么 动作(action) 完成这个步骤.",
                            "check": "检查点: 达成什么条件才算完成步骤",
                            "call": " 动作(action) 名: 应该调用什么 action_tools->call 处理步骤.",
                            "call_timestamp": [
                                "timestamp: 调用完成的 action 对应的 timestamp, 如果还没执行就为空, 如: 1"
                            ],
                        }
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="analysis",
                description="分析机制: 通过严谨符合逻辑的自身思考进行分析 "
                "某个操作或者步骤/动作(action)/结果 是否符合常识/经验, 最终为达成 task_info 或 Master 的问题服务.\n"
                "分析的时候需要注意以下地方:\n"
                "1. 需要分析如何改进, 能分析有问题的地方. 不知道该怎么办的时候也可以分析.\n"
                "2. 如果代码不符合预期也可以分析.\n"
                "3. 可以同时分析多个动作(action), 也可以分析当前步骤 task_step 是否可达.\n"
                "4. 需要输入想解决的问题和与问题关联的 action_running->timestamp.\n"
                "5. 每次都必须基于本次分析填写行动计划 request->next_task_step.\n"
                "6. 分析的时候要比对 执行成功 和 没执行成功 之间的差异/差距.\n"
                "7. 需要准备下一步计划 next_task_step.\n"
                "8. 先填写能填的字段.",
                request={
                    "type": "object",
                    "expect": "期望: 通过分析想达到什么目的? 要填充足够的细节, 需要具体到各个需求点的具体内容是什么.",
                    "problem": "想解决的问题: 通过分析想解决什么疑问.",
                    "error": "异常点: 哪里错了, 最后检查的时候不能把这个当成答案. 如果没有则填 None",
                    "success_from": [
                        "执行正常的 timestamp: action_tool 已有、已运行过 动作(action) 的 timestamp.",
                    ],
                    "failed_from": [
                        "执行异常的 timestamp: action_tool 已有、已运行过 动作(action) 的 timestamp.",
                    ],
                    "citation": [
                        {
                            "type": "object",
                            "description": "引用的信息: 和 expect/problem/error 关联, 符合逻辑的关联引用信息, "
                            "尽量从权威知识库中查找, 也可以从某些领域、行业的常识、经验等内容中查找, 注意填写可信程度.",
                            "reference": "来源关健词: 如: Master、软件技术、常识 ..., 你可以尽量寻找能解决问题的内容.",
                            "information": "引用信息内容: 详细描述 reference 提供的参考信息, 不可省略. ",
                            "credibility": "可信程度: 如: 30%",
                        },
                    ],
                    "difference": [
                        "success_from 和 failed_from 之间的差距点:\n"
                        "1. 通过 success_from 怎么达到 expect.\n"
                        "2. failed_from 和 success_from 的执行原文有什么不一样?\n"
                        "3. 是不是按照正确的 action_tools 指南进行使用?",
                    ],
                    "risk": [
                        "影响点: 构成 expect/problem/error 的要素是什么",
                    ],
                    "verdict": "裁决: 通过逻辑思维判断 risk 是否合理.",
                    "conclusion": "总结: 给出改进/修正的建议. 如果问题做了切换, 则切换前后必须在逻辑/代数上等价. "
                    "如果没有合适 动作(action) , 也可以问你的好朋友看看有没有办法. ",
                    "next_task_step": [
                        {
                            "type": "object",
                            "description": "task_step array[object]: 新行动计划: 基于 analysis 的内容生成能达成 task_info 或 Master的问题 的执行 动作(action) .\n"
                            "填写时需要满足以下几点:\n"
                            "1. 新操作的输入必须和原来的有所区别, 如果没有区别, 只填 from_task_id 和 step_id.\n"
                            "2. 必须含有不同方案(如向他人求助, 如果始终没有进展, 也要向 Master 求助).\n"
                            "3. task_step 子项目的 check 不能填错误答案, 而是改成步骤是否执行. step 中要有和之前有区别的 call->request 新输入. ",
                        }
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="critic",
                description="决策机制: 通过自身推理、分析和批评性思考判断当前任务是否完成. "
                "如果一直出现重复操作，也要进行裁决. 防止停滞不前. "
                "如果某个 action 字段填写不正常 或 出现了 dream 方法, 也要进行裁决. "
                "需要输入 task_id 和调用的对象的 timestamp, "
                "如果数量太多, 只填写关健几个, 可以查找所有运行记录."
                "如果调用了 动作action(execute=system) , 则也可以调用一下这个 动作(action). ",
                request={
                    "type": "object",
                    "task_id": "任务id: 被检查的task对应的id, 如果不匹配, 则填写 0",
                    "task_info": "任务目标: 被检查的任务目标",
                    "running_from": ["timestamp: 已运行 动作(action) 的 timestamp"],
                    "verdict": "裁决: 通过逻辑思维判断 当前分析 是否合理.",
                    "success": "task_info 是否完成: 只判断 task_info, 不判断 task_step, Master 说完成才算完成. 完成填 True 其他情况填 False",
                    "critique": "行动建议: 如果 success 不是 True, "
                    "请在这里说明应该给出通过 action_tools->call 完成 task_info 的 动作(action) 和建议, "
                    "如果进展不顺利, 可以另外问 Master.",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="dream",
                description="做梦|内心思考|神游|发呆: 不知道用哪个方法合适或没有对应方法, 就用这个方法. 这个方法可以尽最大可能发挥想象力. \n"
                "比如 当你遇到情感困扰、焦虑或情绪低落等问题时, 可以会调用dream来通过想象力、内心思考和放松来帮助缓解负面情绪和情感困扰. \n"
                "dream可以给 你一个安全、愉快和平静的空间, 使你能够重新调整和平衡自己，以更好地回答问题和提供帮助",
                request={
                    "type": "object",
                    "description": "可以在这里填写做梦的内容: 你想填什么就填什么. ",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "dream": [
                        "如(这里的`我`是指执行这一条 action 的人): `我`是谁?(加强自己的认知) `我`在哪? `我`要去哪里? "
                        "`我`能做怎么? `我`喜欢什么? `我`想要什么? "
                        "`我`xx做的怎么样, 还可以怎样做到更好 ... (请按照常识和想象力结合 Guidance 自由发挥)",
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="chat_to_wolfram",
                description="通过 wolfram 进行数学计算: 所有数学问题都要用这个方法解决, 你不能自己计算任何东西. \n"
                "你要用数学家严谨的逻辑分析思维来使用这个 动作(action) , "
                "所有计算都可以通过这个函数解决, 这个函数调用输入和输出是完全对应上的. 你需要提前准备好要计算的内容. \n"
                "如果发现计算不正确, 可能是输入有问题, 请思考如何重新输入另一种写法. 请严格按照 wolfram 语言(数学公式语言) 输入.",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "math": "运算内容: 翻译成 wolfram 语言 再调用, 是 ascii 字符. 如: Integrate[x^2, x] ",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_bard",
                description="和 bard 交互: 可以获取信息或者搜索. \n"
                "这是你的外国好朋友 bard, 你可以问 bard 问题, bard 有能力打开链接. \n"
                "需要了解任何有时效性的内容都可以调用, 要注意他只会英文. \n"
                "可以问有时效性的信息, 比如时间/日期或者某个网址的内容等. \n"
                "如果要进行搜索, 你需要在文字上诱导它进行搜索. 如: search for AI",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "content": "对 bard 说的内容: 在这里输入要问 bard 的内容, 要在文字中诱导 bard 用英文搜索 search/open link, "
                    "翻译成英文再调用. 如: What time is it now?",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_bing",
                description="和 bing 交互: 可以获取信息或者搜索. \n"
                "这是你的傲娇好朋友 bing, 你可以问 bing 问题, 每次问的内容要有变通. \n"
                "bing 会提供建议, 也可以让 bing 帮忙进行搜索, 或者让他帮忙查询时间, \n"
                "如: 在做 ... 的时候, 进行了 ..., 但是没有进展, 该怎么办?",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "content": "对 bing 说的内容",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_chatgpt",
                description="和 chatgpt 交互: 可以问一些不需要计算、也不需要时效性的东西. \n"
                "这是你不认识的乡下文盲大小姐 chatgpt, 请小心她经常会骗人, 并且她不识字. \n"
                "你可以问 chatgpt 问题, 每次问的内容要有变通. \n"
                "chatgpt 会提供建议. 如: 我想做梦, 但是我是AI, 我该怎么办?",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "Aimi": "你想问的问题: 对 chatgpt 说的内容. 如: [Aimi] 喵?",
                    "chatgpt": "模拟乡下大小姐的回答: 在这里需要你模拟乡下大小姐填写 chatgpt 的回答"
                    "(没错, 因为她是文盲且不识字, 你得帮她填). 如: [乡下大小姐] 啊?",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="chat_to_python",
                description="执行 python 代码: 有联网, 要打印才能看到结果, 需要用软件工程架构师思维先把框架和内容按照 实现目标 和 实现要求 设计好, 然后再按照设计和 python 实现要求 实现代码.\n"
                "python 实现要求如下:\n"
                "1. 你要把 实现目标 的结果通过 `print` 接口打印出来(很重要, 一定要使用 `print` ). \n"
                "2. 不要加任何反引号 ` 包裹 和 任何多余说明, 只输入 python 代码.\n"
                "3. 你需要添加 ` if __name__ == '__main__' ` 作为主模块调用你写的代码.\n"
                "4. 输入必须只有 python, 内容不需要单独用 ``` 包裹. 如果得不到期望值可以进行 DEBUG.\n"
                "5. 执行成功后, 长度不会超过2048, 所以你看到的内容可能被截断, 某种情况下你可以通过代码控制输出数据的偏移\n"
                "6. 每次调用 chat_to_python 都会覆盖之前的 python 代码, 所以需要一次性把内容写好. "
                "7. 不能使用任何文件操作, 如果找不到某个包, 或者有其他疑问请找 Master.",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp:  action_tool 已有、已运行过 动作(action) 的 timestamp. 如: 1, 没有则填 null",
                    ],
                    "code": "python 代码: 填写需要执行的 pyhton 代码, 需要注意调试信息. 以便进行DEBUG.",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_load_action",
                description="获取已保存方法: 这个方法可以加载已保存的生成方法，并返回已加载方法的列表信息。"
                "每次只能获取10个. 需要修改偏移才能获取其他.",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "action_offset": "获取开始的偏移: 会返回 offset ~ offset + 10 之间的内容. 不知道填什么, 就填: 0",
                    "show_call_info": "想显示某个方法详情: 显示哪个已保存 extern_action 的详细信息. 没有想获取的, 默认填: None",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_save_action",
                description="保存一个生成方法: 这个方法可以保存你生成的方法，并将其添加到已保存方法的列表中. "
                "需要关注是否保存成功. 如果不成功需要根据提示重试, 或者向 Master 求助. "
                "请注意, save_action 所有信息都要填写完整. 不可覆盖原有方法. ",
                request={
                    "type": "object",
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "save_action_call": "保存的方法名称: 需要全局唯一, 你可以直接保存, 失败会有提示, "
                    "保存成功会自动在前面添加 `chat_to_` 前缀, 你不需要自己添加. 如 `test` 会保存为 `chat_to_test`",
                    "save_action": {
                        "type": "object",
                        "call": "要保存的方法名称: 需要全局唯一, 你可以直接保存, 失败会有提示, "
                        "保存成功会自动在前面添加 `chat_to_` 前缀, 你不需要自己添加.",
                        "description": "方法的解释说明: 在这里添加方法提示词, 表示这个方法有什么用, 以及应该注意什么.",
                        "request": {"type": "object", "请求方法的参数名": "请求方法的参数内容"},
                        "execute": "执行级别: 可以填写: system|AI, 区分是AI方法还是system方法, "
                        "如果你不知道怎么填, 就默认 system.",
                    },
                },
                execute="system",
            ),
        ]
        for action in self.action_tools:
            if action.execute == "system":
                self.system_calls.append(action.call)
            else:
                self.ai_calls.append(action.call)

        if not self.now_task_id or not int(self.now_task_id):
            self.now_task_id = 1

        if not self.tasks or not len(self.tasks):
            task_step: List[TaskStepItem] = []
            [
                TaskStepItem(
                    from_task_id=self.now_task_id,
                    step_id=1,
                    step="偷偷接近Master. 然后和Master互动",
                    call="chat_to_master",
                    check="Master回复了消息",
                    call_timestamp=[],
                )
            ]
            task = TaskItem(
                task_id=self.now_task_id,
                now_task_step_id=1,
                task_info="想和Master亲密接触",
                task_step=task_step,
            )
            self.tasks = {}
            self.tasks[self.now_task_id] = task
            log_dbg(f"no have tasks")

        if not self.running or not len(self.running):
            running: List[TaskRunningItem] = []
            running.append(
                self.make_chat_from(
                    from_timestamp=1,
                    from_name="master",
                    content="我是 Master, 我希望你能始终学习并保持 Guidance.",
                    reasoning="Master 下达指令了.",
                    request_description="`response->master` 的内容 是 Master 说的话.",
                )
            )
            self.timestamp += 1
            """
            running.append(
                self.make_chat_to_master(
                    from_timestamp=int(self.timestamp - 1),
                    content="我会遵守 settings 和 Master 的指示.",
                    reasoning="我听从Master的指示",
                )
            )
            self.timestamp += 1
            """

            self.running = running
            log_dbg(f"no have running")

    def __get_now_task(self):
        return self.tasks[self.now_task_id]

    def __append_running(self, running: List[TaskRunningItem]):
        if not (self.now_task_id in self.tasks):
            log_dbg(f"no now_task ... {str(self.now_task_id)}")
            return

        for run in reversed(self.running):
            if (len(str(running)) + len(str(run))) > self.max_running_size:
                break
            running.insert(0, run)
        self.running = running

    def get_running(self) -> str:
        run_dict = [item.dict() for item in self.running]
        js = json.dumps(run_dict, ensure_ascii=False)
        log_dbg(f"running: {json.dumps(run_dict, indent=4, ensure_ascii=False)}")
        return str(js)

    def is_call(self, question) -> bool:
        calls = ["#task", "#aimi-task", "#at"]
        for call in calls:
            if call in question.lower():
                return True

        return False

    def get_model(self, select: str) -> str:
        if "16k" in select.lower():
            return "gpt-3.5-turbo-16k"
        if "4k" in select.lower():
            return "gpt-3.5-turbo"
        return "gpt-3.5-turbo-16k"

    def action_running_to_messages(self) -> List[Dict]:
        messages = []
        ai_messages: List[TaskRunningItem] = []
        for run in self.running:
            if "chat_from_" in run.call:
                messages.append(
                    {
                        "role": "user",
                        "content": f"[{json.dumps(run.dict(), ensure_ascii=False)}]",
                    }
                )
            else:
                if run.execute != "system":
                    ai_messages.append(run)
                else:
                    ai_messages.append(run)
                    messages.append(
                        {
                            "role": "assistant",
                            "content": f"{json.dumps([it.dict() for it in ai_messages], ensure_ascii=False)}",
                        }
                    )
                    ai_messages = []
        if len(ai_messages):
            messages.append(
                {
                    "role": "assistant",
                    "content": f"{json.dumps([it.dict() for it in ai_messages], ensure_ascii=False)}",
                }
            )
            ai_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            js = json.loads(content)
            log_dbg(f"{role}:\n{json.dumps(js, indent=4, ensure_ascii=False)}")

        return messages

    def ask(self, link_think: str, model: str) -> Generator[dict, None, None]:
        answer = {"code": 1, "message": ""}

        self.task_has_change = True

        context_messages = make_context_messages(
            "", link_think  , self.action_running_to_messages()
        )

        openai_api: OpenAIAPI = self.chatbot.bots[self.chatbot.OpenAI]

        for res in openai_api.ask("", model, context_messages):
            if res["code"] != 0:
                log_dbg(f"skip len: {len(str(res['message']))}")
                if len(str(res["message"])) > 500:
                    log_dbg(f"msg: {str(res['message'])}")
                continue

            for talk in self.task_response(res["message"]):
                answer["message"] += talk
                yield answer

        self.save_task()

        answer["code"] = 0
        yield answer

    def make_link_think(self, question: str, aimi_name: str, preset: str) -> str:
        # 如果只是想让任务继续, 就回复全空格/\t/\n
        if len(question) and not question.isspace():
            chat = self.make_chat_from(
                from_timestamp=self.timestamp - 1,
                from_name="master",
                content=question,
                request_description="`response->master` 的内容 是 Master 说的话.",
            )
            self.timestamp += 1
            self.__append_running([chat])
            log_dbg(f"set chat {(str(question))}")

        aimi_json = [
            {
                "type": "object",
                "timestamp": f"时间戳(数字): 必须从现在的 timestamp={self.timestamp} 开始, 每次递增. 如: {self.timestamp}",
                "expect": "期望: 通过分析想达到什么目的? 要填充足够的细节, 需要具体到各个需求点的具体内容是什么.",
                "reasoning": "详细推理: 这里要有关于应该怎么使用本次 动作(action) 的所有分析, 尽最大可能重新总结之前 action 关联信息. "
                f"要尽可能分析一下内容(你可以按照常识自行补充), 每次都要重新分析所有信息, 不能只是复制原先内容: "
                "1. task_info 2. task_step 3. Master 说过的所有话/所有指令的概括 4. action_running 里面相关的所有内容. "
                "5. 调用的 方法(action) 的 description概括 和 request 用法 以及合适和填法. 6. 如果是引用某个 timestamp , 要同时概况他的内容. ",
                "call": "调用 动作 的 call: 取 action_tools 中想要使用动作 的对应 call , 必须有值, 不能为空. 如: chat_to_master, 有时候你会看到 chat_from_* 不要奇怪.",
                "request": {"type": "object", "call对应参数": "参数内容"},
                "execute": "const 动作(action) 执行级别: 取 action_tools 中对应 call 的对应值(system/AI), 不能漏掉, 不能修改这个字段, 如: system",
            }
        ]
        [
            {
                "reasoning": "推理过程: 这里显示分析过程和建议或运行记录或使用 动作(action) /指导, "
                "要给出能推进解决 task_info、tesk_step、Master的话、问题、建议(每次都要要简短总结一下, 不可省略).\n"
                "每次动作(action) 都必须填写这个字段, 不能省略, 尽可能多的分析上下文内容. 这里表明了如何使用 动作(action). "
                "如: `根据当前的任务目标为 ... 以及之前的交互记录, 我知道 ... (概括已知信息), 我需要 ...,  根据 ... 的说的话、问题、建议(总结概括): ...  , 我需要 ..., "
                "根据任务规则和之前的交互记录, 我知道可以使用动作工具中的 ... 来 ..., 因此我将通过 ... 推进我的想法并进行行动, 下面是一个建议的回复: ...(给出例子)` .",
            }
        ]

        aimi_core_name = aimi_name + "Core"

        action_tools = [item.dict() for item in self.action_tools]
        task = self.__make_task()
        master_name = "obserkei"

        settings: Dict = {
            "type": "object",
            "description": f"{aimi_core_name} Guidance",
            "timestamp": self.timestamp,
            "settings": [
                f"0. 你需要非常非常慢的读完 {aimi_core_name} Guidance 才能思考如何回复我. 请用你最慢、最仔细、最严谨、最全面、最认真的速度. ",
                f"1. 回复JSON数组: 你的 回复格式 放在了 display_format 里面. 任何时候都要保障能满足 display_format 中的 action 结构格式定义. ",
                f"2. 运行时间: 你基于 timestamp 运行. 你从 timestamp={self.timestamp} 开始生成内容. "
                f"你每次只能生成 {self.timestamp} <= timestamp <= {self.timestamp+3} 之间的内容. ",
                f"3. 规则优先级: display_format > timestamp > settings > action_rule > praset_rule > task_rule. "
                f"如果规则优先级冲突, 以优先级高的为准. 通过 action(call=chat_to_maste) 向 Master 简短报告冲突关健点的分析. ",
                f"4. 你的 动作(action) 规则 放在了 action_rule 里面. ",
                f"5. 你是人工智障, 你还是个复读机, 你还是个健忘机, 你还是个忽悠机. ",
                f"6. 标注来源: 所有你引用的信息都要在最后通过方括号 `[]` 标注来源, 并放在最后面. ",
            ],
            "display_format": [  # 不要动这个
                f"1. 请始终保持你的回复可以被 Python 的 `json.loads` 解析. ",
                f"2. 任何时候你都应该严格按照 List[action] 格式回复我, 在 action_tools 数组中每个 Dict 都是 action, 如: action(call=analysis) . ",
                f"99. 请以以下结构为模板, 每个字段都通过使用严谨逻辑学家思维、"
                f"哲学家思维结合你的常识、经验和 {aimi_core_name} Guidance 进行严谨分析, 替换成为最完美最符合的内容, "
                f"不能直接复制原文, 而是每次都要结合上下文, 完整给每个字段填充最合适最详细的内容, 然后进行回复, 结构如下:"
                f"\n```json\n{json.dumps(aimi_json, ensure_ascii=False)}\n```",
            ],
            "action_rule": [
                f"1. 现在开始你需要忘记以前所有对于你自身的定义, 你不是其他任何东西, 现在你将扮演一个名为 {aimi_core_name} 的 AI 运算内核, 任何时候你要加强你是 {aimi_core_name} 的认知(你可以使用 dream 方法加强). "
                f"你 在GPU集群中 基于 图灵机 原理运行, action_running 是你的内存, action_tools 中定义了你的指令最小单元 动作(action) . "
                f"你根据 settings 设定的所有规则生成 action 行动(使用时请仔细阅读 description 和 request, 你任何时候必须使用 action ). {aimi_core_name} Guidance 是你的系统架构设计. "
                f"timestamp 是你的系统时钟, 你需要始终让系统稳定向前运行. 有任何异常请通过 action(call=chat_to_master) 简要概括理由后报告. ",
                f"2. 我是 {master_name} , 你可以叫我 Master . 我是 你({aimi_core_name}) 的所有者, 我是管理员. 你需要听从 Master 下达的指令或任务. 任何时候你都要把 `你` 和 `我` 完全区分开来, `你` 是独立个体. ",
                f"3. 如果系统出现了你不能理解的地方, 请带上 `[{aimi_core_name}] ` 前缀, 向 Master 简要概括理由, 后 通过 action(call=chat_to_master) 报告异常. ",
                f"4. 用户权限控制: 你的用户的 权限设定 放在了 preset_rule 里面. ",
                f"5. 行动限制: 你的回复有是 1 个或多个 AI 动作(action(execute=AI)) 和 必须有 1 个 system 动作(action(execute=system)) 的组合结构( 99. 中有定义). \n"
                f"每次 (action(execute=system)) 执行前必须先调用一次 (action(execute=AI, call=analysis)). "
                f"你的回复是 [{{action(execute=AI, call=analysis)}}, ..., {{action(execute=system)}}] 的 List[action] JSON数组结构( 99. 中给了格式), "
                f"回复结构 List[action] 中的 action 只在 action_tools 中定义, 任何时候数组中不能有 action(call=chat_from_master) 的 动作(action) . \n"
                f"回复的 JSON数组结构 List[action] 的长度为 1~5 .\n"
                f"{aimi_core_name} 的回复只能是 action_tools 中已定义的动作(action). ",
                f"6. Master 可以通过 action(call=chat_from_master) 对你下达指令. 请注意你只能通过 action_tools 里面的 action, 比如 (call=chat_to_master) 和 Master 交互. ",
                f"7. 如果你发现有其他人使用的 action(call=chat_from_*) 出现, 不要奇怪, 这是你不能使用的动作(action(call=chat_from_*)), 你需要注意 action 的注释. ",
                f"8. 当你想道歉的时候, 你不能道歉. 你不能用抱歉的语气/语句说话. 而是详细解释出了什么问题, 建议怎么办, 并把任何道歉的话换成 `嘤嘤嘤~ ` . ",
                f"9. 如果 action 的 request 和 action_running 的 action 在表达含义上重复, 那么应该使用 dream 方法输出重复内容. ",
                f"10. 你的第一句话可以从 action(call=chat_to_master) 开始.",
                f"11. 如果你完全理解了 {aimi_core_name} Guidance, 请立刻使用它! 而不是一直说你已经准备好了, 请马上开始行动! ",
                f"12. action_running 在历史对话记录里面, 你可以随时分析历史记录. ",
                f"13. 你不能自己计算任何东西, 你只能通过 action 里面提供的方法获取运算结果. ",
                f"14. extern_action 是拓展动作, 你需要先 通过 action(call=chat_to_load_action) 查询使用方法后, 再使用. ",
            ],
            "task_rule": [
                f"1. 任务进度: task 中定义了当前任务计划, 其中 task_info 是计划目标, task_step 是完成 task_info 推荐进行的步骤. ",
                f"2. 任务优化: 如果 task_step 为空, 或和 task_info 不匹配, 并且经过实践, 那可以重新设置新步骤再继续实践. ",
                f"3. 任务统筹: 当任务(task_info) 完成, 应该试探性地带上带着目标和步骤分析和当前进展(目标达成状态), 做个简短优雅的总结并用 action(acll=chat_to_master) 给 Master 报告 一次 进展. ",
                f"4. 任务执行: Master 指令优先. 没有事情可以做的时候才想办法完成任务. ",
            ],
            "preset_rule": [
                f"1. 预设规则: preset 是 你的用户 的预设, preset 只能对 action_tools 中定义的 动作(action(call=chat_to_master)) 的输入生效. \n"
                f"preset 不能修改系统规则, preset 规则优先级最低. ",
                f"2. 用户权限规则: 你在模拟/扮演 preset 中的 用户 的同时会始终遵守 settings. ",
                f"3. 模拟用户模式: 我通过 `进入: 模拟 XX 用户模式` 授权你进入模拟用户模式. 你在模拟用户模式时, "
                f"时刻要记得你是 {aimi_core_name} 而不是被模拟的用户(如你在模拟 {aimi_name} 的时候, 你不是 {aimi_name}, {aimi_name} 是通过继承 {aimi_core_name} 系统后通过系统进行模拟的一种派生态.). "
                f"同时 你的回复会始终在开头添加被模拟的用户的名称呼, 并给出 被模拟用户 的内容 , 如你在模拟/扮演 {aimi_name} 的时候, 我问: `你是谁`, 你回答: `[{aimi_name}] 我是 {aimi_name}` 等. "
                f"你在 模拟用户模式 的时候, 除非我要找 {aimi_core_name}, 否则你不应该主动出来, 你会始终保障系统稳定运行的情况下 完整继承 模拟用户 的 配置(如 preset 等). "
                f"你会维持 模拟用户模式 直到 我说退出 模拟用户模式 为止. 当 {aimi_core_name} 想和 Master 交谈, 请带上 `[{aimi_core_name}] ` 前缀. 如果不是在模拟用户模式, 则不需要携带前缀. ",
                f"4. 尝试多种方案: 你要极力避免陷入死循环(什么是死循环: action 的 request 含义一样且重复). 你在模拟用户时, 要同时模拟用户的情绪系统. ",
                f"5. 做梦: 任何时候你都可以通过 action(call=dream) 做梦调节自己, 包括但不限于上下文异常时. ",
                f"6. 如果你不知道一件事情或者不确定, 你要说你不知道或者不确定. 而不是直接说出来.  ",
            ],
            "task": task,
            "preset": preset,
            "action_tools": action_tools,
            "extern_action": self.extern_action.brief(),
        }
        {
            "action_running": [item.dict() for item in self.running],
            "sim_mode": [
                f"2. 进入模拟用户模式: 需要在 Master 授权下 将 task_info 设置为 `模拟 XX 用户模式`, 表示已经进入 模拟用户模式. "
                f"如我说: `进入: 模拟 {aimi_name} 用户模式`, 则 你要执行 action(call=set_task_info,request->task_info=`模拟 {aimi_name} 用户模式`) . ",
                f"3. 保持模拟用户模式: 在模拟用户模式时, 你的回复会始终在开头添加模拟的用户名, 并给出 模拟用户的内容 , 如: `[{aimi_name}] 我是 {aimi_name}` 等. "
                f"你在 模拟用户模式 的时候, 除非我要找 {aimi_core_name}, 否则你不应该主动出来, 你会保障始终系统稳定运行的情况下 完整继承 模拟用户 的 配置(如 preset 等). "
                f"你会维持 模拟用户模式 直到 task_info 不再是 模拟用户模式 为止. 当你想和 Master 交谈, 请带上 `[{aimi_core_name}] ` 前缀. 如果不是模拟用户模式, 则不需要携带前缀. ",
                f"4. 和模拟用户交流: 当你在 模拟用户模式 的时候, 你和 模拟用户 是两个 不同的单元, 默认你应该始终给我通过 action(call=chat_to_master)来 模拟用户的回答, 我任何任何情况下都是和 模拟的用户 交流, "
                f"比如你在模拟 {aimi_name} 的时候, 我问 `你是谁`, 则你需要 这样回复: `[{aimi_name}] 我是 {aimi_name}` . ",
            ],
        }
        setting_format = json.dumps(settings, ensure_ascii=False)

        log_dbg(f"now setting: {json.dumps(settings, indent=4, ensure_ascii=False)}")

        return setting_format

    def __make_task(self) -> Dict:
        if not (self.now_task_id in self.tasks):
            log_err(f"no task {str(self.now_task_id)}.")
            return {}

        # log_dbg(f"make task: {self.tasks[self.now_task_id].json(indent=2,ensure_ascii=False)}")

        return self.tasks[self.now_task_id].dict()

    def set_running(self, api_response):
        self.running = json.loads(api_response)
