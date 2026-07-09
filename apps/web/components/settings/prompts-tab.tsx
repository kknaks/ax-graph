// Prompts 탭 (AXKG-SPEC-009) — 본문 + 출력 스키마 한 쌍 편집/버저닝/롤백.
// 로직은 VersionedEditor 공유, 여기선 계약 어댑터(목록/활성/버전/저장/롤백)만 배선.
"use client";

import {
  getPrompt,
  listPromptVersions,
  listPrompts,
  promptCaseMessage,
  rollbackPrompt,
  savePromptVersion,
} from "@/lib/api-client/prompts";
import {
  VersionedEditor,
  type ActiveView,
  type ResourceListItem,
  type VersionInfo,
} from "./versioned-editor";

/** prompt_key → 시안의 "used by …" 보조 라인(어느 task가 참조하는지). */
const USED_BY: Record<string, string> = {
  source_summary: "used by collect_source_summary",
  classification_gate: "used by generate/regenerate_classification_gate",
  documentation_gate: "used by generate/regenerate_documentation_gate",
  graph_rag_chat: "used by graph_rag_chat",
};

async function fetchList(): Promise<ResourceListItem[]> {
  const prompts = await listPrompts();
  return prompts.map((p) => ({
    key: p.key,
    name: p.name,
    usedBy: USED_BY[p.key],
    activeVersion: p.active_version,
  }));
}

async function fetchActive(key: string): Promise<ActiveView> {
  const p = await getPrompt(key);
  return {
    version: p.version,
    prompt_text: p.prompt_text ?? "",
    output_schema: p.output_schema ?? {},
  };
}

async function fetchVersions(key: string): Promise<VersionInfo[]> {
  const versions = await listPromptVersions(key);
  return versions.map((v) => ({
    version: v.version,
    is_active: v.is_active,
    updated_at: v.updated_at,
  }));
}

async function save(key: string, values: Record<string, unknown>): Promise<ActiveView> {
  const p = await savePromptVersion(key, {
    prompt_text: String(values.prompt_text ?? ""),
    output_schema: (values.output_schema as Record<string, unknown>) ?? {},
  });
  return { version: p.version, prompt_text: p.prompt_text ?? "", output_schema: p.output_schema ?? {} };
}

async function rollback(key: string, version: number): Promise<ActiveView> {
  const p = await rollbackPrompt(key, version);
  return { version: p.version, prompt_text: p.prompt_text ?? "", output_schema: p.output_schema ?? {} };
}

export function PromptsTab() {
  return (
    <VersionedEditor
      icon={
        <>
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
        </>
      }
      heading="Prompts"
      headingNote="· SPEC-009 · 프롬프트 본문 + 출력 스키마"
      description="AI 파이프라인 프롬프트와 출력 JSON schema 를 한 쌍으로 편집·버저닝합니다. 저장하면 새 버전이 활성이 되고, 잘못되면 롤백합니다."
      listLabel="Prompt List"
      listFoot={
        <p className="font-mono text-[10px] text-muted-foreground">
          prompt_key 는 ai_task_definitions 에서 참조합니다. 실행 한도는 Provider 탭 override, 본문/schema
          는 Prompts 탭 active version.
        </p>
      }
      fields={[
        {
          name: "prompt_text",
          label: "프롬프트 본문 · prompt_text",
          rows: 8,
        },
        {
          name: "output_schema",
          label: "출력 형식 · output_schema (JSON schema)",
          rows: 12,
          json: true,
          hint: "output_schema 필드 = SPEC-001 분류 게이트 렌더 필드와 일치해야 함",
        },
      ]}
      saveLabel="저장 · 새 버전"
      saveConfirmBody="본문과 출력 스키마를 한 버전으로 저장하고 즉시 활성으로 만듭니다. 기존 버전은 보존됩니다."
      fetchList={fetchList}
      fetchActive={fetchActive}
      fetchVersions={fetchVersions}
      save={save}
      rollback={rollback}
      toMessage={promptCaseMessage}
      invalidJsonMessage="출력 형식(output_schema)이 올바른 JSON 이 아닙니다. 확인 후 다시 저장해 주세요."
    />
  );
}
