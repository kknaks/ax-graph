// Templates 탭 (AXKG-SPEC-010) — 문서 뼈대 md(body) 단일 편집/버저닝/롤백.
// Prompts 미러(output_schema 없음). VersionedEditor 공유, 어댑터만 배선.
// 주의: BE templates 라우트는 이 작업 시점 stub — T-010 확정 시 필드 정합(리포트 참조).
"use client";

import {
  TEMPLATE_FLOW,
  getTemplate,
  listTemplateVersions,
  listTemplates,
  rollbackTemplate,
  saveTemplateVersion,
  templateCaseMessage,
} from "@/lib/api-client/templates";
import {
  VersionedEditor,
  type ActiveView,
  type ResourceListItem,
  type VersionInfo,
} from "./versioned-editor";

async function fetchList(): Promise<ResourceListItem[]> {
  const templates = await listTemplates();
  return templates.map((t) => ({
    key: t.key,
    name: t.name ?? t.key,
    usedBy: TEMPLATE_FLOW[t.key],
    activeVersion: t.active_version,
  }));
}

async function fetchActive(key: string): Promise<ActiveView> {
  const t = await getTemplate(key);
  return { version: t.version, body: t.body ?? "" };
}

async function fetchVersions(key: string): Promise<VersionInfo[]> {
  const versions = await listTemplateVersions(key);
  return versions.map((v) => ({
    version: v.version,
    is_active: v.is_active,
    updated_at: v.updated_at,
  }));
}

async function save(key: string, values: Record<string, unknown>): Promise<ActiveView> {
  const t = await saveTemplateVersion(key, { body: String(values.body ?? "") });
  return { version: t.version, body: t.body ?? "" };
}

async function rollback(key: string, version: number): Promise<ActiveView> {
  const t = await rollbackTemplate(key, version);
  return { version: t.version, body: t.body ?? "" };
}

export function TemplatesTab() {
  return (
    <VersionedEditor
      icon={
        <>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h8M8 17h5" />
        </>
      }
      heading="Templates"
      headingNote="· SPEC-010 · 문서 뼈대(frontmatter + 섹션)"
      description="AI 가 생성하는 지식 문서의 템플릿(뼈대)을 md 로 편집·버저닝합니다. 코드레포 templates/product/** 와는 별개입니다."
      banner={
        <p className="mb-4 flex items-center gap-1.5 rounded-md bg-secondary/50 p-2 text-[10px] text-muted-foreground">
          <svg
            className="h-3.5 w-3.5 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M12 8v4l3 3" />
            <circle cx="12" cy="12" r="9" />
          </svg>
          생성 문서 frontmatter 에 적용 템플릿 버전을 스탬프합니다 (예:{" "}
          <span className="font-mono">template: reference@v3</span>).
        </p>
      }
      listLabel="Template List"
      listFoot={
        <p className="font-mono text-[10px] text-muted-foreground">
          문서 타입 4종 = reference · permanent · project_baseline · concept
          (main 3종은 destination 매핑, concept 은 문서화③ 조립 동봉)
        </p>
      }
      fields={[
        {
          name: "body",
          label: "문서 뼈대 · body (frontmatter 필드 + 섹션 구조)",
          rows: 18,
          hint: "뼈대(SPEC-010) + 프롬프트(SPEC-009) + output_schema 를 문서화 게이트 초안 AI 가 조립",
        },
      ]}
      saveLabel="저장 · 새 버전"
      saveConfirmBody="문서 뼈대(body)를 새 버전으로 저장하고 즉시 활성으로 만듭니다. 이후 생성 문서 frontmatter 에 이 버전이 스탬프됩니다."
      fetchList={fetchList}
      fetchActive={fetchActive}
      fetchVersions={fetchVersions}
      save={save}
      rollback={rollback}
      toMessage={templateCaseMessage}
    />
  );
}
