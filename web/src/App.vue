<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { request } from './api/client'
import { sliceText } from './api/report'
import { useRunEvents } from './composables/useRunEvents'

const sample = '12개월 정기예금, 세전 단리 최고 연 4.5%!\n누구나 조건 없이 확정 수익을 받아보세요.\n100만 원부터 가입 가능합니다.'
const text = ref(''), selected = ref(''), search = ref(''), picker = ref(false), asOf = ref('2026-10-21')
const products = ref([]), loading = ref(true), loadError = ref(''), active = ref(null), filter = ref('전체'), tab = ref('original')
const toast = ref(''), feedback = ref({}), rejectId = ref(null), reason = ref('')
let toastTimer
const { status: mode, report, error, tasks, receivedVerdicts, reconnecting, start: run, clear } = useRunEvents()
const running = computed(() => mode.value === 'running')
const product = computed(() => products.value.find(p => p.id === selected.value))
const matches = computed(() => products.value.filter(p => (p.company_name + p.product_name).includes(search.value)))
const preview = computed(() => product.value?.options.find(o => o.term_months === 12))
const level = { potential_violation: '위반 소지', caution: '주의', needs_review: '사람 확인 필요' }
const tone = { potential_violation: 'red', caution: 'amber', needs_review: 'slate' }
const types = { missing_notice: '필수사항 누락', disclosure_mismatch: '공시 사실 대조', exaggeration: '단정·과장 표현', misleading_guarantee: '보장·오인 표현' }
const available = computed(() => (report.value?.judgment?.verdicts ?? receivedVerdicts.value).map(v => {
  const claim = report.value?.extraction?.claims.find(c => c.id === v.claim_id)
  const rules = (report.value?.regulations ?? []).filter(r => v.evidence_ids.includes(r.chunk_id))
  const comparison = report.value?.comparisons.find(c => c.claim_id === v.claim_id)
  return { ...v, level: level[v.severity], tone: tone[v.severity], type: types[v.violation_type],
    quote: claim?.quote ?? `클레임 ${v.claim_id ?? v.checklist_item_id}`, claim, rules, comparison }
}))
const visible = computed(() => available.value.filter(i => filter.value === '전체' || i.level === filter.value))
const counts = computed(() => Object.fromEntries(Object.values(level).map(l => [l, available.value.filter(i => i.level === l).length])))
const stepNames = ['문구 추출', '규정 근거 조회', '공시 수치 대조', 'AI 1차 판정']
const stepKinds = ['extract', 'retrieve', 'factcheck', 'judge']
const stage = computed(() => {
  const current = tasks.value.find(t => t.status === 'running')
  if (current) return stepKinds.indexOf(current.task_id.split(':')[0])
  return mode.value === 'done' ? 4 : 0
})
const currentTask = computed(() => tasks.value.find(t => t.status === 'running')?.task_id ?? 'supervisor')
const taskStatus = { pending: '대기', running: '진행 중', succeeded: '완료', skipped: '건너뜀', failed: '실패', blocked: '실행 불가' }
const segments = computed(() => {
  if (tab.value === 'revised') {
    let revised = text.value
    const fixes = available.value.filter(i => i.suggested_revision && i.claim?.span)
      .sort((a, b) => b.claim.span.start - a.claim.span.start)
    let boundary = Array.from(text.value).length
    for (const item of fixes) {
      const { start, end } = item.claim.span
      if (end > boundary) continue
      revised = sliceText(revised, 0, start) + item.suggested_revision + sliceText(revised, end)
      boundary = start
    }
    return [{ text: revised }]
  }
  const highlights = available.value.filter(i => i.claim?.span).sort((a, b) => a.claim.span.start - b.claim.span.start)
  const result = []; let cursor = 0
  for (const item of highlights) {
    const { start, end } = item.claim.span
    if (start < cursor || sliceText(text.value, start, end) !== item.claim.quote) continue
    result.push({ text: sliceText(text.value, cursor, start) }, { text: sliceText(text.value, start, end), id: item.id, tone: item.tone })
    cursor = end
  }
  result.push({ text: sliceText(text.value, cursor) })
  return result
})
function notify(message) { toast.value = message; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 2500) }
function reset() { if (running.value) return; clear(); text.value = ''; active.value = null; feedback.value = {}; filter.value = '전체'; tab.value = 'original' }
async function start() {
  if (!text.value.trim() || running.value) return
  active.value = null; feedback.value = {}; filter.value = '전체'; tab.value = 'original'
  await run({ ad_text: text.value, product_id: selected.value || null, as_of_date: asOf.value })
}
function reject() { if (!reason.value.trim()) return; feedback.value[rejectId.value] = '기각 (화면만 반영)'; rejectId.value = null; reason.value = '' }
onMounted(async () => {
  try { const [p, health] = await Promise.all([request('/api/products'), request('/api/health')]); products.value = p; asOf.value = health.snapshot_date }
  catch (e) { loadError.value = e.message }
  finally { loading.value = false }
})
onUnmounted(() => clearTimeout(toastTimer))
</script>

<template>
 <div class="app-shell">
  <aside class="sidebar">
   <a class="brand" href="#" @click.prevent="reset"><span class="brand-icon">r<span>↗</span></span>redpen<span class="brand-dot">.</span></a>
   <div class="workspace-label">WORKSPACE</div>
   <button class="nav-item selected" @click="notify('현재 광고 사전심의 화면입니다')"><span class="nav-icon">▤</span> 광고 사전심의 <span class="nav-arrow">›</span></button>
   <div class="side-note"><span class="tiny-icon">✧</span><strong>더 명확한 근거,<br>더 확신 있는 검토.</strong><p>광고 문구부터 규정 근거까지,<br>RedPen과 함께 확인하세요.</p><span class="note-line"></span></div>
   <div class="sidebar-bottom"><div class="demo-pill"><i></i> AI CONNECTED DEMO</div><p>규정 조회·공시 스냅샷 사용</p><div class="profile"><span class="avatar">M</span><div><strong>심의 담당자</strong><small>준법감시팀</small></div></div></div>
  </aside>
  <main>
   <header class="topbar"><div>워크스페이스 <span>/</span> <b>광고 사전심의</b></div><div class="top-right"><span class="mock-label">DEMO</span><span class="top-divider"></span>AI 1차 검토</div></header>
   <div class="page-content">
    <div class="heading-row"><div><div class="eyebrow">FINANCIAL AD REVIEW</div><h1>광고 사전심의<span>.</span></h1><p>광고의 작은 문구까지, 근거를 바탕으로 꼼꼼하게.</p></div><button class="button secondary new-review" :disabled="running" @click="reset">＋ 새 검토</button></div>
    <div class="review-meta"><span class="document-icon">▤</span><strong>예·적금 광고 검토</strong><span class="tag">스냅샷 데이터</span><div class="meta-right"><span class="status-dot" :class="{ pulse: running }"></span>{{running?'검토 진행 중':mode==='input'?'작성 중':mode==='failed'?'검토 실패':'검토 종료'}}<span class="meta-date">기준일 {{asOf}}</span></div></div>
    <div class="data-notice">ⓘ 규정은 설정한 공급자에서 조회하며, 공시는 저장된 스냅샷을 사용합니다. 실제 모델로 검토하며 원천 검증은 미수행입니다.</div>
    <p v-if="loadError" class="error-banner" role="alert">서버 연결 실패: {{loadError}} · FastAPI 실행 여부를 확인한 뒤 새로고침하세요.</p>
    <div v-if="error" class="error-banner" role="alert">{{error}} <button v-if="mode==='failed'" class="button secondary" @click="start">같은 문안 재시도</button><button v-if="mode==='failed'" class="button secondary" @click="clear">문안 수정</button></div>
    <section v-if="mode!=='input'" class="progress-panel">
     <div class="progress-title"><span class="success-ring">{{running?'◌':mode==='failed'?'!':'✓'}}</span><strong>{{running?(reconnecting?'진행 연결을 복구하고 있어요':'광고 문안을 검토하고 있어요'):mode==='failed'?'검토가 완료되지 않았습니다':'AI 1차 검토가 끝났습니다 · 근거 검증 미수행'}}</strong><span>{{running?currentTask:report?.run_status}}</span></div>
     <div class="steps"><div v-for="(step,index) in stepNames" :key="step" class="step" :class="{complete:stage>index,current:running&&stage===index}"><span class="step-circle">{{stage>index?'✓':index+1}}</span>{{step}}<span v-if="index<3" class="step-connector"></span></div></div>
     <details v-if="tasks.length" class="task-details"><summary>Supervisor 작업 내역 ({{tasks.length}}개)</summary><div v-for="task in tasks" :key="task.task_id"><code>{{task.task_id}}</code><span>{{taskStatus[task.status]}} · {{task.attempts ?? task.attempt ?? 0}}회 {{task.feedback ?? task.reason ?? ''}} {{task.error_code ?? ''}} <code v-if="task.diagnostic_id">진단: {{task.diagnostic_id}}</code></span></div></details>
    </section>
    <div class="review-grid">
     <section class="panel source-panel">
      <div class="panel-heading"><div><span class="section-number">01</span><h2>광고 문안</h2></div><span class="muted">{{text.length}} / 10,000자</span></div>
      <div v-if="mode==='input'" class="input-area"><div class="input-label">검토할 광고 문안을 입력하세요<button @click="text=sample">예시 불러오기 ↗</button></div><textarea v-model="text" maxlength="10000" placeholder="제목, 금리, 가입 조건 등 광고 문안을 붙여넣어 주세요." aria-label="광고 문안"></textarea></div>
      <template v-else><div class="source-tabs"><button :class="{active:tab==='original'}" @click="tab='original'">광고 원문</button><button :class="{active:tab==='revised'}" @click="tab='revised'">수정 제안 미리보기</button></div><div class="ad-paper"><div class="paper-top"><span>AD COPY</span><span>{{tab==='original'?'원본':'미검증 수정 제안'}}</span></div><div class="ad-copy"><template v-for="(segment,index) in segments" :key="index"><button v-if="segment.id" class="highlight" :class="[segment.tone,{focused:active===segment.id}]" @click="active=segment.id;filter='전체'">{{segment.text}}</button><span v-else>{{segment.text}}</span></template></div></div><p v-if="tab==='revised'" class="product-footnote preview-note">제안이 없는 문구는 원문을 유지합니다. 확정 심의 문안이 아닙니다.</p></template>
      <div class="product-section"><div class="product-title"><h3>공시 대조 상품 <span>선택</span></h3><button v-if="mode==='input'" @click="picker=!picker">{{product?'변경':'상품 선택'}} ⌄</button><span v-else class="product-check">{{product?'저장된 공시 스냅샷':'공시 대조 미수행'}}</span></div>
       <div v-if="picker&&mode==='input'" class="product-picker"><input v-model="search" placeholder="은행명 또는 상품명 검색" aria-label="공시 상품 검색"/><button @click="selected='';picker=false">상품 선택 건너뛰기</button><div class="product-options"><button v-for="p in matches" :key="p.id" @click="selected=p.id;picker=false">{{p.company_name}} · {{p.product_name}} <small>{{p.product_type==='deposit'?'예금':'적금'}} / {{p.disclosure_month}}</small></button></div><p v-if="!matches.length">공시 상품을 찾지 못했습니다.</p></div>
       <div v-if="product" class="product-box"><div class="bank-icon">₩</div><div class="product-name"><small>{{product.company_name}}</small><strong>{{product.product_name}}</strong></div><span class="tag">공시 {{product.disclosure_month}}</span></div>
       <div v-if="product&&preview" class="rates"><div><span>12개월 {{preview.interest_type_name}} 기본 금리</span><strong>{{preview.base_rate ?? '미공시'}}<small>%</small></strong></div><div><span>동일 옵션 최고 금리</span><strong>{{preview.max_rate ?? '미공시'}}<small>%</small></strong></div></div>
       <p class="product-footnote">{{product?'표시 금리는 옵션 미리보기입니다. 실제 대조는 광고의 기간·유형·조건을 확인해 수행합니다.':'상품을 선택하지 않으면 금리 대조를 건너뜁니다.'}}</p>
       <label class="date-field">검토 기준일 <input v-model="asOf" type="date" :disabled="mode!=='input'"/></label>
      </div>
      <div v-if="mode==='input'" class="start-wrap"><button class="button primary" :disabled="!text.trim()||loading||!!loadError" @click="start">✧ AI 검토 시작 <span>→</span></button><p>로컬 모델은 수 분 걸릴 수 있습니다. 모델 설정은 서버 환경변수를 사용합니다.</p></div>
     </section>
     <section class="results">
      <div class="results-heading"><div><span class="section-number">02</span><h2>검토 리포트</h2><span class="ai-label">AI 1차 의견 · 미검증</span></div><span class="muted">{{available.length}}개 확인사항</span></div>
      <div v-if="mode==='input'||(running&&!available.length)" class="empty-state"><span class="empty-icon">{{running?'✧':'▧'}}</span><h3>{{running?'Supervisor가 검토를 진행하고 있습니다':'광고 한 문장에서 시작하세요'}}</h3><p>{{running?'실제 단계 진행은 위 작업 내역에서 확인할 수 있습니다.':'광고를 입력하면 문구별 판정과 근거를 이곳에 표시합니다.'}}</p></div>
      <template v-else>
       <div class="summary-cards"><button v-for="(count,label) in counts" :key="label" :class="{chosen:filter===label}" @click="filter=filter===label?'전체':label"><span>{{label}}</span><strong>{{count}}<small>건</small></strong></button></div>
       <div class="results-toolbar"><button @click="filter='전체'">{{filter}} {{visible.length}}</button><span>{{running?'판정 수신 중':'원천 검증 미수행'}}</span></div>
       <div v-if="!available.length" class="data-notice">{{mode==='failed'?'유효한 판정 리포트를 생성하지 못했습니다. 작업 내역을 확인하세요.':'이 실행에서 판정 항목이 생성되지 않았습니다. 적합 판정을 의미하지는 않습니다.'}}</div>
       <article v-for="(issue,index) in visible" :key="issue.id" class="verdict-card" :class="[issue.tone,{expanded:active===issue.id}]">
        <button class="verdict-top" @click="active=active===issue.id?null:issue.id"><span class="issue-index">{{index+1}}</span><div><div class="verdict-badges"><span class="severity" :class="issue.tone">{{issue.level}}</span><span class="issue-type">{{issue.type}}</span><span v-if="feedback[issue.id]" class="feedback-done">{{feedback[issue.id]}}</span></div><h3>{{issue.quote}}</h3></div><span class="expand-chevron">{{active===issue.id?'−':'＋'}}</span></button>
        <div v-if="active===issue.id" class="verdict-detail"><p>{{issue.reason}}</p>
         <div v-if="issue.comparison" class="evidence"><div class="evidence-title">금리 대조 · {{issue.comparison.status}}</div><p>{{issue.comparison.reason}}</p><div v-if="issue.comparison.disclosed_rate!==null" class="comparison"><div><span>광고</span><strong>{{issue.comparison.advertised_rate}}%</strong></div><span>→</span><div><span>공시 옵션</span><strong>{{issue.comparison.disclosed_rate}}%</strong></div><span class="difference">{{issue.comparison.difference_pp}}%p 차이</span></div></div>
         <div v-for="rule in issue.rules" :key="rule.chunk_id" class="evidence"><div class="evidence-title"><span>{{rule.law_name}} 제{{rule.article_no}}조</span><span>원천 검증 미수행</span></div><p class="law-text">{{rule.text}}</p><div class="evidence-meta">시행일 {{rule.effective_from}} · <a :href="rule.source_url" target="_blank" rel="noopener noreferrer">출처 열기 ↗</a></div></div><div v-if="!issue.rules.length" class="evidence"><p>{{running?'리포트 완료 후 근거 연결을 확인할 수 있습니다.':'이 판정에 연결된 규정 근거가 없습니다.'}}</p></div>
         <div v-if="issue.suggested_revision" class="suggestion"><span>✧ 수정 제안 · 미검증</span><p>{{issue.suggested_revision}}</p></div>
         <div class="card-actions"><span>의견은 화면에서만 반영됩니다</span><button @click="rejectId=issue.id">기각</button><button class="agree" @click="feedback[issue.id]='동의 (화면만 반영)'">✓ 동의</button></div>
        </div>
       </article>
      </template>
     </section>
    </div>
    <footer><span class="footer-brand">redpen.</span><span>규정 조회·공시 스냅샷 · 실제 AI 호출</span><span>원천 검증 미수행 · 최종 심의는 담당자 확인</span></footer>
   </div>
  </main>
  <div v-if="toast" class="toast" role="status">{{toast}}</div>
  <div v-if="rejectId" class="modal-backdrop" @click.self="rejectId=null"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="reject-title"><h2 id="reject-title">판정 기각</h2><p>의견은 현재 화면에서만 반영됩니다.</p><textarea v-model="reason" aria-label="기각 사유" placeholder="기각 사유를 입력하세요"></textarea><div><button class="button secondary" @click="rejectId=null">취소</button><button class="button primary" :disabled="!reason.trim()" @click="reject">기각</button></div></section></div>
 </div>
</template>
