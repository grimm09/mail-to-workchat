from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ..models import AppConfig, BotConfig
from ..security import SecurityError, resolve_under, sanitize_error
from ..storage.database import CaseRecord, Database
from ..templates.repository import TemplateError, TemplateRepository
from ..templates.cases import refresh_case_draft
from .commands import Command, CommandError, parse_command
from .models import ChatEvent, ChatResponse
from .templates import TemplateProposalResult, VersionedTemplateManager


_ADMIN_COMMANDS = {
    "ignore",
    "template_update",
    "template_confirm",
    "template_cancel",
    "template_rollback",
}


class InteractionService:
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        templates: TemplateRepository,
    ):
        self.config = config
        self.database = database
        self.templates = templates
        self.template_manager = VersionedTemplateManager(templates, database)
        self.drafts_dir = config.app.data_dir / "drafts"

    def _bot(self, event: ChatEvent) -> BotConfig:
        bot = next((item for item in self.config.bots if item.id == event.bot_id), None)
        if bot is None or not bot.enabled:
            raise SecurityError("机器人未启用")
        if bot.platform != event.platform:
            raise SecurityError("机器人平台与事件不匹配")
        return bot

    @staticmethod
    def _identity_hash(platform: str, kind: str, value: str) -> str:
        digest = hashlib.sha256(f"{platform}\n{kind}\n{value}".encode("utf-8")).hexdigest()
        return f"sha256:{digest[:20]}"

    def _authorize(self, event: ChatEvent, bot: BotConfig) -> None:
        if not self.config.interaction.enabled:
            raise SecurityError("互动模式未启用")
        now = datetime.now(timezone.utc)
        age = (now - event.occurred_at).total_seconds()
        if age > self.config.interaction.event_ttl_seconds or age < -60:
            raise SecurityError("消息已过期或时间异常")
        if event.chat_id not in bot.allowed_chat_ids:
            raise SecurityError("该会话不在授权白名单中")
        if event.user_id not in bot.allowed_user_ids:
            raise SecurityError("该用户不在授权白名单中")
        if event.is_group and bot.require_mention and not event.mentioned_bot:
            raise SecurityError("群聊指令必须明确提及机器人")

    def _cap(self, text: str) -> str:
        limit = self.config.interaction.response_chars
        if len(text) <= limit:
            return text
        suffix = "\n\n[内容已截断，请在本机查看完整记录]"
        return text[: max(0, limit - len(suffix))].rstrip() + suffix

    def _reserve(
        self,
        event: ChatEvent,
        command: str,
        target: str,
    ) -> tuple[bool, str, str]:
        user_hash = self._identity_hash(event.platform, "user", event.user_id)
        chat_hash = self._identity_hash(event.platform, "chat", event.chat_id)
        reserved, previous = self.database.reserve_interaction_event(
            event_id=event.canonical_id,
            bot_id=event.bot_id,
            platform=event.platform,
            chat_hash=chat_hash,
            user_hash=user_hash,
            command=command,
            target=target,
            request_hash=hashlib.sha256(
                f"{event.occurred_at.isoformat()}\n{event.is_group}\n{event.mentioned_bot}\n{event.text}".encode("utf-8")
            ).hexdigest(),
        )
        return reserved, previous, user_hash

    def _complete(self, event: ChatEvent, response: ChatResponse) -> ChatResponse:
        capped = self._cap(response.text)
        self.database.complete_interaction_event(
            event.canonical_id,
            outcome=response.outcome,
            response=capped,
        )
        return ChatResponse(capped, response.outcome)

    def _rejected(self, event: ChatEvent, message: str) -> ChatResponse:
        response = ChatResponse(f"拒绝执行：{message}", "denied")
        try:
            reserved, _, _ = self._reserve(event, "denied", "")
        except SecurityError:
            return response
        # An authorization failure never reads a previous response, even for a known ID.
        return self._complete(event, response) if reserved else response

    @staticmethod
    def _cached(previous: str) -> ChatResponse:
        return ChatResponse(previous, "duplicate") if previous else ChatResponse("该消息正在处理，请稍后重试。", "retry")

    def handle(self, event: ChatEvent) -> ChatResponse:
        try:
            bot = self._bot(event)
            self._authorize(event, bot)
        except SecurityError as exc:
            return self._rejected(event, str(exc))

        try:
            command = parse_command(event.text)
        except CommandError as exc:
            try:
                reserved, previous, _ = self._reserve(event, "invalid", "")
            except SecurityError as denied:
                return ChatResponse(f"拒绝执行：{denied}", "denied")
            if not reserved:
                return self._cached(previous)
            return self._complete(event, ChatResponse(str(exc), "invalid"))

        if command.name in _ADMIN_COMMANDS and event.user_id not in bot.admin_user_ids:
            return self._rejected(event, "该指令仅允许管理员使用。")
        try:
            reserved, previous, actor_hash = self._reserve(event, command.name, command.target)
        except SecurityError as denied:
            return ChatResponse(f"拒绝执行：{denied}", "denied")
        if not reserved:
            return self._cached(previous)

        try:
            response = self._dispatch(command, event, actor_hash)
        except (CommandError, TemplateError, SecurityError, ValueError) as exc:
            response = ChatResponse(f"未执行：{sanitize_error(exc)}", "rejected")
        except Exception as exc:  # keep platform callbacks alive without exposing internals
            response = ChatResponse(
                f"处理失败：{type(exc).__name__}。请查看本地审计记录。",
                "error",
            )
        return self._complete(event, response)

    def _dispatch(self, command: Command, event: ChatEvent, actor_hash: str) -> ChatResponse:
        if command.name == "help":
            return ChatResponse(self._help())
        if command.name == "query":
            return ChatResponse(self._query(command.target))
        if command.name == "reply":
            return ChatResponse(self._reply(command.target))
        if command.name == "ignore":
            return ChatResponse(self._ignore(command.target, event.canonical_id, actor_hash))
        if command.name == "template_update":
            proposal = self.template_manager.propose_update(
                command.target,
                reply_subject=command.reply_subject,
                reply_body=command.reply_body,
                actor_hash=actor_hash,
                event_id=event.canonical_id,
            )
            return ChatResponse(self._proposal_response(proposal, actor_hash))
        if command.name == "template_confirm":
            revision = self.template_manager.apply(command.target, actor_hash=actor_hash)
            return ChatResponse(f"模板更新已批准并启用：{command.target} → v{revision}")
        if command.name == "template_cancel":
            self.template_manager.cancel(command.target)
            return ChatResponse(f"模板更新已取消：{command.target}")
        if command.name == "template_history":
            return ChatResponse(self._template_history(command.target))
        if command.name == "template_rollback":
            proposal = self.template_manager.propose_rollback(
                command.target,
                command.revision or 0,
                actor_hash=actor_hash,
                event_id=event.canonical_id,
            )
            return ChatResponse(self._proposal_response(proposal, actor_hash))
        raise CommandError("unsupported command")

    @staticmethod
    def _help() -> str:
        return """可用指令：
查询                       列出最近待处理邮件
查询 <邮件编号>            查看邮件状态
回复 <邮件编号>            显示已批准模板生成的草稿（不会发邮件）
忽略 <邮件编号>            标记为忽略（管理员）
模板更新 <模板ID>          提交模板新版本（管理员）
主题: Re: {subject}
正文:
新的模板正文
模板确认 <变更编号>        批准并启用新版本（管理员）
模板取消 <变更编号>        取消待审批变更（管理员）
模板历史 <模板ID>          查看可回滚版本
模板回滚 <模板ID> <版本>   创建回滚提案（管理员）"""

    @staticmethod
    def _one_line(value: str, limit: int = 300) -> str:
        return " ".join(value.replace("\x00", "").split())[:limit]

    def _case(self, reference: str) -> CaseRecord:
        case = self.database.find_case(reference)
        if case is None:
            raise ValueError(f"未找到邮件编号：{reference}")
        return case

    def _query(self, reference: str) -> str:
        if not reference:
            cases = self.database.list_cases(status="open", limit=8)
            if not cases:
                return "当前没有待处理邮件。"
            lines = ["最近待处理邮件："]
            for case in cases:
                lines.append(
                    f"- {case.case_ref} | {self._one_line(case.subject, 80)} | "
                    f"草稿:{case.draft_status or '无'}"
                )
            return "\n".join(lines)
        case = self._case(reference)
        lines = [
            f"邮件编号：{case.case_ref}",
            f"状态：{case.status}",
            f"邮箱：{self._one_line(case.account_label, 120)}",
            f"规则：{case.rule_id}",
            f"发件人：{self._one_line(case.sender_email, 180)}",
            f"主题：{self._one_line(case.subject, 240)}",
            f"接收时间：{case.received_at}",
            f"回复草稿：{case.draft_status or '无'}",
        ]
        for key, value in sorted(case.extracted.items()):
            lines.append(f"{key}：{self._one_line(value, 240)}")
        if case.snippet:
            lines.extend(("摘要：", self._one_line(case.snippet, 500)))
        return "\n".join(lines)

    def _reply(self, reference: str) -> str:
        case = self._case(reference)
        case = refresh_case_draft(case, self.templates, self.database, self.drafts_dir)
        if case.draft_status != "ready" or not case.draft_path:
            raise ValueError(
                f"{case.case_ref} 没有可复制的已批准草稿（当前：{case.draft_status or '无'}）"
            )
        draft_path = resolve_under(self.drafts_dir, Path(case.draft_path))
        if not draft_path.is_file():
            raise ValueError(f"{case.case_ref} 的草稿文件不存在")
        with draft_path.open("r", encoding="utf-8") as stream:
            content = stream.read(self.config.interaction.response_chars + 1)
        if len(content) + 120 > self.config.interaction.response_chars:
            raise ValueError("草稿超过群消息长度限制；请在本机打开完整草稿，不提供截断的可复制回复")
        return f"{case.case_ref} 的回复草稿（仅供人工复制，不会自动发送）：\n\n{content}"

    def _ignore(self, reference: str, event_id: str, actor_hash: str) -> str:
        case = self._case(reference)
        if case.status == "ignored":
            return f"{case.case_ref} 已经是忽略状态。"
        if not self.database.set_case_status(
            case.message_key,
            status="ignored",
            event_id=event_id,
            actor_hash=actor_hash,
            action="ignore",
        ):
            raise ValueError(f"无法更新邮件状态：{case.case_ref}")
        return f"已将 {case.case_ref} 标记为忽略并取消待发送通知；已在途的通知可能仍送达。不会删除邮件或草稿。"

    def _proposal_response(self, proposal: TemplateProposalResult, actor_hash: str) -> str:
        if len(proposal.diff) + 350 > self.config.interaction.response_chars:
            self.template_manager.cancel(proposal.change_id)
            raise TemplateError("完整差异超过群消息限制，提案已取消；请在本机审核，不允许批准截断的差异")
        if not self.config.interaction.template_confirmation_required:
            revision = self.template_manager.apply(proposal.change_id, actor_hash=actor_hash)
            return f"模板已按单步模式更新：{proposal.change_id} → v{revision}"
        diff = proposal.diff or "（没有可显示的差异）"
        return (
            f"模板变更已建立：{proposal.change_id}\n"
            f"请核对差异后发送：模板确认 {proposal.change_id}\n"
            f"取消请发送：模板取消 {proposal.change_id}\n\n{diff}"
        )

    def _template_history(self, template_id: str) -> str:
        revisions = self.template_manager.revisions(template_id)
        if not revisions:
            return "该模板尚无版本记录；首次批准聊天更新时会保存当前版本。"
        lines = [f"模板 {template_id} 的版本："]
        for item in revisions[:20]:
            lines.append(
                f"- v{item.revision} | {item.reason} | 操作人 {item.changed_by_hash[-8:]}"
            )
        return "\n".join(lines)
