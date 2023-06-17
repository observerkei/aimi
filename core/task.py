import json5
import json
import os
from typing import Dict, Any, List, Generator, Optional, Union
from pydantic import BaseModel, constr

from tool.openai_api import OpenAIAPI
from tool.wolfram_api import WolframAPI
from tool.bard_api import BardAPI
from tool.bing_api import BingAPI
from tool.config import Config
from tool.util import log_dbg, log_err, log_info, make_context_messages, write_yaml
from core.sandbox import Sandbox

class TaskStepItem(BaseModel):
    from_task_id: str
    step_id: str
    step: str
    check: str
    call: str
    call_timestamp: List[str]


class ActionToolItem(BaseModel):
    call: str
    description: str
    request: Any
    execute: constr(regex="system|AI")


class TaskRunningItem(BaseModel):
    timestamp: str = ""
    reasoning: Optional[Union[str, None]] = None
    call: str
    request: Any
    execute: constr(regex="system|AI")


class TaskItem(BaseModel):
    task_id: str
    task_info: str
    now_task_step_id: str = ""
    task_step: List[TaskStepItem] = []


class Task:
    type: str = "task"
    tasks: Dict[str, TaskItem] = {}
    action_tools: List[ActionToolItem] = []
    now_task_id: str = "1"
    aimi_name: str = "Aimi"
    running: List[TaskRunningItem] = []
    max_running_size: int = 16 * 1000
    timestamp: int = 1
    wolfram_api: WolframAPI
    bard_api: BardAPI
    bing_api: BingAPI
    openai_api: OpenAIAPI

    def task_response(self, res: str) -> Generator[dict, None, None]:
        def get_json_content(answer: str) -> str:
            start_index = answer.find("```json\n[")
            if start_index == -1:
                start_index = answer.find("[")
            else:
                start_index += 8
            if start_index != -1:
                end_index = answer.rfind("]\n```", start_index)
                if end_index != -1:
                    answer = answer[start_index : end_index + 1]
                else:
                    end_index = answer.rfind("]", start_index)
                    if end_index != -1:
                        if "]" == answer[-1]:
                            # 防止越界
                            answer = answer[start_index:]
                        else:
                            answer = answer[start_index : end_index + 1]
                        # 去除莫名其妙的解释说明
            return answer

        log_dbg(f"now task: {str(self.tasks[self.now_task_id].task_info)}")

        response = ""
        try:
            answer = get_json_content(res)

            # 忽略错误.
            # decoder = json.JSONDecoder(strict=False)
            # data = decoder.decode(answer)
            data = json5.loads(answer)

            # fix no execute.
            for action in data:
                if "execute" in action:
                    continue
                for tool in self.action_tools:
                    if action["call"] != tool.call:
                        continue
                    action["execute"] = tool.execute
                    log_dbg(f"fill call({tool.call}) execute: {tool.execute}")

            tasks = [TaskRunningItem(**item) for item in data]

            running: List[TaskRunningItem] = []
            task_cnt = 1
            for task in tasks:
                try:
                    log_dbg(
                        f"[{task_cnt}] get task: {str(task.call)} : {str(task)}\n\n"
                    )

                    task_cnt += 1
                    task_response = None
                    if task.reasoning:
                        log_dbg(f"{str(task.call)} reasoning: {str(task.reasoning)}")

                    if task.call == "chat_to_master":
                        content = str(task.request)
                        log_dbg(f"Aimi: {content}")
                        yield content + "\n"
                    elif task.call == "chat_from_master":
                        log_err(
                            f"{str(task.call)}: AI try predict Master: {str(task.request)}"
                        )
                        continue
                    elif task.call == "set_task_step":
                        task_id: str = task.request["task_id"]
                        now_task_step_id: str = task.request["now_task_step_id"]
                        task_step: List[TaskStepItem] = task.request["task_step"]
                        self.set_task_step(task_id, now_task_step_id, task_step)
                    elif task.call == "set_task_info":
                        task_id: str = task.request["task_id"]
                        task_info: str = task.request["task_info"]
                        now_task_step_id: str = task.request["now_task_step_id"]
                        self.set_task_info(task_id, task_info, now_task_step_id)
                    elif task.call == "critic":
                        self.critic(task.request)
                    elif task.call == "analysis":
                        self.analysis(task.request)
                    elif task.call == "chat_to_wolfram":
                        response = self.chat_to_wolfram(task.request)
                        task_response = self.make_chat_from("wolfram", response)
                    elif task.call == "chat_to_bard":
                        response = self.chat_to_bard(task.request)
                        task_response = self.make_chat_from("bard", response)
                    elif task.call == "chat_to_bing":
                        response = self.chat_to_bing(task.request)
                        task_response = self.make_chat_from("bing", response)
                    elif task.call == "chat_to_python":
                        response = self.chat_to_python(task.request)
                        task_response = self.make_chat_from("python", response)
                    else:
                        log_err(f"no suuport call: {str(self.call)}")
                        continue

                    if (len(str(running)) + len(str(task))) < self.max_running_size:
                        task.timestamp = str(self.timestamp)
                        self.timestamp += 1
                        running.append(task)
                    else:
                        log_dbg(f"task len overload: {len(str(task))}")
                    if task_response and (
                        (len(str(running)) + len(str(task_response)))
                        < self.max_running_size
                    ):
                        task_response.timestamp = str(self.timestamp)
                        self.timestamp += 1
                        running.append(task_response)

                except Exception as e:
                    log_err(f"fail to load task: {str(e)}: {str(task)}")
            self.__append_running(running)
            log_dbg(f"update running success: {len(running)}")
        except Exception as e:
            log_err(f"fail to load task res: {str(e)} : \n{str(res)}")

        yield ""

    def chat_to_python(self, code: str) -> str:
        log_info(f"code:\n```python\n{code}\n```")
        ret = Sandbox.write_code(code)
        if not ret:
            return 'system error: write code failed.'
        result = Sandbox.run_code()
        log_info(f"code run result:\n{result}")
        if len(result) > 2 * 1024:
            log_dbg(f"result too long trim {len(result)} to 2048")
            result = result[:2*1024]
        return result

    def chat_to_bing(self, request: str) -> str:
        if not request or not len(request):
            return "request error"

        answer = ""
        for res in self.bing_api.ask(request):
            if res["code"] != 0:
                continue
            answer = res["message"]

        return answer

    def make_chat_from(self, from_name: str, content: str) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=str(self.timestamp),
            call=f"chat_from_{from_name}",
            request=content,
            execute="system",
        )
        return chat

    def chat_to_bard(self, request: str) -> str:
        if not request or not len(request):
            return "request error"

        answer = ""
        for res in self.bard_api.ask(request):
            if res["code"] != 0:
                continue
            answer = res["message"]
            log_dbg(f"res bard: {str(answer)}")

        return answer

    def chat_to_wolfram(self, request: str) -> str:
        if not request or not len(request):
            return "request error"
        answer = ""
        for res in self.wolfram_api.ask(request):
            if res["code"] != 0:
                continue
            answer = res["message"]

        return answer

    def make_chat_from_master(self, content: str) -> TaskRunningItem:
        return self.make_chat_from("master", content)

    def make_chat_to_master(self, content: str, reasoning: str = "") -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=str(self.timestamp),
            reasoning=reasoning,
            call=f"chat_to_master",
            request=content,
            execute="system",
        )
        self.timestamp += 1
        return chat

    def set_task_step(
        self, task_id: str, now_task_step_id: str, task_step: List[TaskStepItem]
    ):
        for _, task in self.tasks.items():
            if task_id != task.task_id:
                continue
            task.now_task_step_id = now_task_step_id
            task.task_step = task_step
            log_info(
                f"set task[{str(task_id)}] now_step_id: {str(now_task_step_id)} step: {str(task_step)}"
            )
            return task.task_step

    def set_task_info(self, task_id: str, task_info: str, now_task_step_id: str):
        for _, task in self.tasks.items():
            if task_id != task.task_id:
                continue
            log_info(
                f"set task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id}"
            )
            self.now_task_id = task_id
            task.task_info = task_info
            task.now_task_step_id = now_task_step_id
            return task
        task = TaskItem(
            task_id=task_id,
            task_info=task_info,
            now_task_step_id=now_task_step_id,
            task_step=[],
        )
        self.now_task_id = task_id
        self.tasks[task_id] = task

        log_info(
            f"set new task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id} "
        )
        return task

    def analysis(self, request):
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            log_info(f"analysis: {js}")
        except Exception as e:
            log_err(f"fail to analysis {str(e)}")

    def critic(self, request):
        try:
            if request["success"] == "True" or request["success"] == True:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                log_info(f"success: True, task complate: {str(task_info)}")

                self.now_task_id = str(int(self.now_task_id) + 1)
                new_task = TaskItem(
                    task_id=self.now_task_id,
                    task_info="当前没有事情可以做, 找Master聊天吧...",
                    now_task_step_id="1",
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

    def __init__(self):
        try:
            self.__load_task()
            self.__init_task()
            self.openai_api = OpenAIAPI()
            self.wolfram_api = WolframAPI()
            self.bing_api = BingAPI()
            self.bard_api = BardAPI()
        
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

                tasks[id] = TaskItem(
                    task_id=task_id,
                    task_info=task_info,
                    now_task_step_id=now_task_step_id,
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
            self.now_task_id = task_config["now_task_id"]
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        return True

    def save_task(self):
        save_path = Config.task_config

        try:
            save_dir = os.path.dirname(save_path)
            if save_dir != "." and not os.path.exists(save_dir):
                os.makedirs(save_dir)

            tasks = {task_id: task.dict() for task_id, task in self.tasks.items()}
            running = [run.dict() for run in self.running]

            save_obj = {
                "now_task_id": self.now_task_id,
                "tasks": tasks,
                "timestamp": self.timestamp,
                "running": running,
            }

            write_yaml(save_path, save_obj)

            log_info(f"save {self.type} done: " + str(save_path))
            ret = True

        except Exception as e:
            log_err(f"fail to save {self.type}: {str(e)}, file:{save_path}")
            ret = False

        return ret

    def __init_task(self):
        self.action_tools: List[ActionToolItem] = [
            ActionToolItem(
                call="chat_to_master",
                description="和 Master 交互: 给Master发送消息进行交互. "
                "你要用严谨逻辑思维来分析调用这个接口. 只能提供可证实的信息, "
                "提供的内容都要有来源. Master在Master的指示下可以临时放开限制. ",
                request="Aimi对Master传达的内容: 可以很丰富, 包含多句话, 要优化内容层次和排版, "
                "如果有数学公式, 则要用latex显示, 每个公式都要单独包裹在单独行的 $$ 中.",
                execute="system",
            ),
            ActionToolItem(
                call="set_task_info",
                description="设定当前任务目标: 填写参数前要分析完毕, "
                "设置目标的时候要同时给出实现步骤, 然后同时调用 set_task_step 方法设置步骤. "
                "Master通过chat_from_master授权时才能调用这个, 否则不能调用这个. "
                "如果要修改任务, 需要Master同意, "
                "如果任务无法完成, 要给出原因然后向Master或者其他人求助.",
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
                            "要显示分析过程和用什么方法完成这个步骤.",
                            "check": "检查点: 达成什么条件才算完成步骤",
                            "call": "方法名: 应该调用什么 action 处理步骤.",
                            "call_timestamp": [
                                "timestamp: 调用完成的action对应的 timestamp, 如果还没执行就为空, 如: 1"
                            ],
                        }
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="analysis",
                description="分析机制: 通过严谨符合逻辑的自身思考进行分析 某个操作是否合理, 最终为 task_info 或Master 的问题服务, "
                "以及如何改进, 能分析有问题的地方. 不知道该怎么办的时候也可以分析."
                "可以同时分析多个动作(action). 需要输入想解决的问题和与问题关联的timestamp.",
                request={
                    "type": "object",
                    "error": "异常点: 哪里错了, 最后检查的时候不能把这个当成答案. 如果没有则填 None",
                    "problem": "想解决的问题: 通过分析想解决什么疑问.",
                    "expect": "期望: 通过分析想达到什么目的.",
                    "running": ["timestamp: 已运行方法的 timestamp"],
                    "risk": ["影响点: 可能导致出现 problem 的原因或者被检查的部分数据内容, 或者达到 expect 需要构成的条件"],
                    "verdict": "裁决: 通过逻辑思维判断 risk 是否合理.",
                    "conclusion": "总结: 给出改进/修正的建议. 如果问题做了切换, 则切换前后必须在逻辑/代数上等价. "
                    "如果没有合适方法, 也可以问你的好朋友看看有没有办法. ",
                    "task_step": "task_step array[object]: 行动计划: 基于 analysis 总结生成执行方法. "
                    "新操作的输入必须和原来的有所区别, 如果没有区别, 只填 from_task_id 和 step_id. 必须含有不同方案(如向他人求助). "
                    "task_step 子项目的 check 不能填错误答案, 而是改成步骤是否执行. ",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="critic",
                description="决策机制: 通过自身思考判断当前任务task_info是否完成."
                "需要输入 task_id 和调用的对象的 timestamp, "
                "如果数量太多, 只填写关健几个, 可以查找所有运行记录."
                "如果调用了 system 方法, 则也必须调用一下这个方法.",
                request={
                    "type": "object",
                    "task_id": "任务id: 被检查的task对应的id",
                    "task_info": "任务目标: 被检查的任务目标",
                    "running": ["timestamp: 已运行方法的 timestamp"],
                    "success": "任务是否完成: 完成填 True 其他情况填 False",
                    "critique": "行动建议: 如果success不是 True, "
                    "请在这里说明应该给出通过 action_tools->call 完成 task_info 的方法和建议, "
                    "如果进展不顺利, 可以另外问Master.",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="chat_to_wolfram",
                description="通过wolfram进行数学计算: 你要用数学家严谨的逻辑分析思维来使用这个方法, "
                "所有计算都可以通过这个函数解决, 这个函数调用输入和输出是完全对应上的. "
                "如果发现计算不正确, 可能是输入有问题, 请思考如何重新输入另一种写法. 请严格按照wolfram语言输入.",
                request="运算内容: 翻译成 wolfram语言 再调用. 如: Integrate[x^2, x] ",
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_bard",
                description="和 bard 交互/回复/响应: 这是你的好朋友 bard, "
                "你可以问 bard 问题, "
                "需要了解任何有时效性的内容都可以调用, 要注意他只会英文."
                "可以问有时效性的信息, 比如时间/日期或者某个网址的内容等.",
                request="对 bard 说的内容: 在这里输入要问bard的内容, 要在文字中诱导 bard 用英文搜索 "
                "翻译成英文再调用. 如: What time is it now?",
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_bing",
                description="和 bing 交互/回复/响应: 这是你的好朋友 bing, "
                "你可以问 bing 问题, "
                "bing 会提供建议, 也可以让 bing 帮忙进行搜索, 或者让他帮忙查询时间, "
                "如: 我在和Master聊天, 但是没有进展, 我该怎么办?",
                request="对 bing 说的内容",
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_python",
                description="执行python代码: 需要用软件工程架构师思维先把框架和内容定好, 然后再把框架实现成代码, 需要主动调用自己写的函数. "
                "执行成功后, 长度不会超过2048, 所以你看到的内容可能被截断, 某种情况下你可以通过代码控制输出数据的偏移. "
                "不能使用任何文件操作, 如果找不到某个包, 或者有其他疑问请找Master.",
                request="需要执行的 pyhton 代码内容",
                execute="system",
            ),
        ]

        if not self.now_task_id or not int(self.now_task_id):
            self.now_task_id = "1"

        if not self.tasks or not len(self.tasks):
            task_step: List[TaskStepItem] = [
                TaskStepItem(
                    from_task_id=self.now_task_id,
                    step_id="1",
                    step="偷偷接近Master. 然后和Master互动",
                    call="chat",
                    check="Master回复了消息",
                    call_timestamp=[],
                )
            ]
            task = TaskItem(
                task_id=self.now_task_id,
                now_task_step_id="1",
                task_info="想和Master亲密接触",
                task_step=task_step,
            )
            self.tasks = {}
            self.tasks[self.now_task_id] = task
            log_dbg(f"no have tasks")

        if not self.running or not len(self.running):
            running: List[TaskRunningItem] = []
            running.append(self.make_chat_from_master("我是Master, 请你请保持设定"))
            self.timestamp += 1
            running.append(self.make_chat_to_master("好", "作为Aimi, 我听从Master的指示"))
            self.timestamp += 1

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

    def ask(self, link_think: str, model: str) -> Generator[dict, None, None]:
        answer = {"code": 1, "message": ""}

        context_messages = make_context_messages(link_think, "", [])

        for res in self.openai_api.ask("", model, context_messages):
            if res["code"] != 0:
                log_dbg(f"skip len: {len(str(res['message']))}")
                if len(str(res["message"])) > 2000:
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
            chat = self.make_chat_from_master(question)
            self.timestamp += 1
            self.__append_running([chat])
            log_dbg(f"set chat {(str(question))}")

        response_format = f"""```json
[
    {{
        "timestamp": "时间戳: 执行当前调用的时间, 每次递增, 从最大 timestamp 开始算.",
        "call": "调用方法: 需要使用哪个 action_tools.",
        "reasoning": "推理过程: 在这里显示分析过程和建议或运行记录或使用方法/指导, 要给出能推进 task_info 的建议.",
        "request": {{
            "对应入参": "对应内容."
        }},
        "execute": "执行类型: 取 action_tools 中对应 call 的对应值(system/AI), 不能漏掉, 不能修改."
    }}
]
```"""

        action_tools = [item.dict() for item in self.action_tools]
        task = self.__make_task()
        settings: Dict = {
            "settings": [
                f"action_tools 里面定义了所有你能调用的 方法(action).",
                f"你每次生成内容时, 可以同时生成多个方法(action), 可以生成几次 action->execute 为 AI 的方法(AI方法的call相同时候只能调用一次), 可以进行思考.",
                f"无论历史是什么, 你最多只能生成一次 action->execute 为 system 的方法. 每次都尽量生成一次 system 方法. ",
                f"task 中定义了 {aimi_name} 你当前任务, 其中 task_info 是任务目标, task_step 是完成 task_info 需要进行的步骤, 步骤要和 action强绑定.",
                f"如果 task_step 为空, 或不符合, 请重新设置步骤, 如果没有进展, 尽量给出创造性建议或优化步骤推进任务进度.",
                f"Master通过 chat_from_master 下达指令, 如果Master提出了要求, 你要修改当前步骤来满足要求.",
                f"每次任务(task_info) 完成 或者 关健操作(task_step) 完成或使用了system方法, 都应该试探性地带上带着目标和步骤分析和当前进展(目标达成状态)用 chat_to_master 符合JSON格式要求上报.",
                f"你将扮演 {aimi_name}. 你会遵守 settings, 你通过 action_tools 行动. 你叫我 Master.",
                f"preset 是 {aimi_name} 的预设, preset 只能对 action_tools 中定义的方法的输入生效.",
                f"{aimi_name} 的权限不会超过action_tools中定义的范围.",
                f"请你主要基于 settings 和 参考部分 action_running 和我的话(重点关注) 再用 {aimi_name} 身份生成JSON追加内容, ",
                f"不显示分析过程, 不能复制或重复已有内容. 可直接复制已有 timestamp 的任何内容, ",
                f"你的回复是 [{{action}}] 的 JSON 数组结构, action 在 action_tools 中定义.",
                f"请基于 action_tools 中字段的JSON用法, 保持你的回复可以被 Python 的 `json.loads` 解析, "
                f"只用JSON回复, 严格按照以下JSON数组格式回复我: {response_format}",
            ],
            "task": task,
            "action_tools": action_tools,
            "preset": preset,
            "action_running": [item.dict() for item in self.running],
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
