<script setup>
import { computed, ref, onUnmounted } from 'vue'
const sample = '당신의 새로운 시작을 응원합니다.\n레드은행과 함께하는 더 나은 내일\n\n레드 정기예금\n최고 연 4.5%\n\n누구나 조건 없이, 확정 수익을 받아보세요.\n복잡한 조건 없이 목돈을 안전하게 키우는 방법.\n지금 가입하고 더 큰 혜택을 만나보세요.\n\n가입 기간 12개월 · 100만 원부터 가입 가능'
const text = ref(sample), mode = ref('done'), tab = ref('original'), active = ref(1), filter = ref('전체'), stage = ref(5), selected = ref('red'), search = ref(''), picker = ref(false), feedback = ref({}), rejectId = ref(null), reason = ref(''), toast = ref('')
let timer, toastTimer
const products = [{ id:'red', bank:'레드은행', name:'레드 정기예금', base:'3.0', max:'3.8' }]
const product = computed(() => products.find(p => p.id === selected.value))
const matches = computed(() => products.filter(p => (p.bank+p.name).includes(search.value)))
const issues = [
 { id:1, level:'위반 소지', tone:'red', type:'공시 사실 불일치', quote:'최고 연 4.5%', title:'광고 금리가 공시 최고 금리와 다릅니다', description:'광고에 표시된 최고 금리가 선택한 상품의 공시 금리보다 0.7%p 높습니다. 우대 조건을 포함한 실제 적용 금리를 확인해 주세요.', fix:'최고 연 3.8% (세전, 우대조건 충족 시)', law:'금융소비자보호법 · 광고 준수사항', evidence:'금융상품의 이자율 등 거래 조건은 소비자가 오인하지 않도록 정확하고 명확하게 표시해야 합니다.' },
 { id:2, level:'위반 소지', tone:'red', type:'보장·오인 표현', quote:'누구나 조건 없이, 확정 수익', title:'가입 조건과 수익을 오인할 수 있습니다', description:'우대금리 적용 조건을 설명하지 않고 모든 가입자에게 동일한 수익이 보장되는 것처럼 표현했습니다.', fix:'가입 조건에 따라 적용 금리가 달라질 수 있습니다.', law:'금융소비자보호법 · 오인 가능 표현', evidence:'상품의 내용과 거래 조건을 사실과 다르게 알리거나 소비자가 잘못 인식할 수 있는 표현을 사용하지 않도록 합니다.' },
 { id:3, level:'주의', tone:'amber', type:'필수사항 누락', quote:'필수 안내사항 미기재', title:'가입 전 확인할 안내사항이 필요합니다', description:'세전·세후 구분, 우대금리 조건, 중도해지 시 적용 금리 등 상품의 주요 안내사항을 추가해 주세요.', fix:'※ 금리는 세전 기준이며, 중도해지 시 약정금리보다 낮은 금리가 적용됩니다.', law:'예금성 상품 · 필수 안내사항', evidence:'광고에는 상품의 주요 내용과 소비자가 유의해야 할 사항을 알아보기 쉽게 안내합니다.' },
 { id:4, level:'사람 확인 필요', tone:'slate', type:'근거 확인 필요', quote:'목돈을 안전하게 키우는 방법', title:'표현의 적정성을 담당자가 확인해 주세요', description:'해당 문구에 대한 직접적인 근거를 확인하지 못했습니다. 광고의 전체 맥락을 함께 검토해 주세요.' }
]
const available = computed(() => product.value ? issues : issues.filter(i => i.id !== 1))
const visible = computed(() => available.value.filter(i => filter.value === '전체' || i.level === filter.value))
const running = computed(() => mode.value === 'running')
const steps = ['문구 추출', '규정 검색', '공시 대조', '위반 판정', '근거 검증']
function notify(message) { toast.value=message; clearTimeout(toastTimer); toastTimer=setTimeout(()=>toast.value='',2500) }
function reset() { clearInterval(timer); mode.value='input'; text.value=''; feedback.value={}; tab.value='original'; filter.value='전체' }
function loadSample() { text.value=sample; selected.value='red'; notify('예시 광고 문안을 불러왔습니다') }
function start() { if(!text.value.trim())return; mode.value='running'; stage.value=0; feedback.value={}; active.value=1; filter.value='전체'; timer=setInterval(()=>{ stage.value++; if(stage.value===5){clearInterval(timer); mode.value='done'} },650) }
function agree(id) { feedback.value={...feedback.value,[id]:'동의 완료'} }
function reject() { if(!reason.value.trim())return; feedback.value={...feedback.value,[rejectId.value]:'기각 완료'}; rejectId.value=null; reason.value='' }
const segments = computed(() => {
 if(tab.value==='revised')return [{ text: text.value.replace('최고 연 4.5%', '최고 연 3.8% (세전, 우대조건 충족 시)').replace('누구나 조건 없이, 확정 수익을 받아보세요.', '가입 조건에 따라 적용 금리가 달라질 수 있습니다.')+'\n\n※ 중도해지 시 약정금리보다 낮은 금리가 적용됩니다.' }]
 return text.value.split(/(최고 연 4\.5%|누구나 조건 없이, 확정 수익|목돈을 안전하게 키우는 방법)/g).map(t=>({text:t,id:t==='최고 연 4.5%'?1:t==='누구나 조건 없이, 확정 수익'?2:t==='목돈을 안전하게 키우는 방법'?4:null}))
})
onUnmounted(()=>{clearInterval(timer);clearTimeout(toastTimer)})
</script>

<template>
 <div class="app-shell">
  <aside class="sidebar">
   <a class="brand" href="#" @click.prevent="mode='done';text=sample"><span class="brand-icon">r<span>↗</span></span>redpen<span class="brand-dot">.</span></a>
   <div class="workspace-label">WORKSPACE</div>
   <button class="nav-item selected" @click="notify('현재 광고 사전심의 화면입니다')"><span class="nav-icon">▤</span> 광고 사전심의 <span class="nav-arrow">›</span></button>
   <div class="side-note"><span class="tiny-icon">✧</span><strong>더 명확한 근거,<br>더 확신 있는 검토.</strong><p>광고 문구부터 규정 근거까지,<br>RedPen과 함께 확인하세요.</p><span class="note-line"></span></div>
   <div class="sidebar-bottom"><div class="demo-pill"><i></i> INTERACTIVE MOCKUP</div><p>예시 데이터로 구성된 화면입니다.</p><div class="profile"><span class="avatar">M</span><div><strong>심의 담당자</strong><small>준법감시팀</small></div><span class="profile-more">···</span></div></div>
  </aside>
  <main>
   <header class="topbar"><div>워크스페이스 <span>/</span> <b>광고 사전심의</b></div><div class="top-right"><span class="mock-label">DEMO</span><span class="top-divider"></span><span class="team-mark">R</span> 레드은행</div></header>
   <div class="page-content">
    <div class="heading-row"><div><div class="eyebrow">FINANCIAL AD REVIEW</div><h1>광고 사전심의<span>.</span></h1><p>광고의 작은 문구까지, 근거를 바탕으로 꼼꼼하게.</p></div><button class="button secondary new-review" @click="reset"><span>＋</span> 새 검토</button></div>
    <div class="review-meta"><span class="document-icon">▤</span><strong>{{mode==='input'?'새 광고 검토':'레드 정기예금 디지털 광고'}}</strong><span class="tag">예·적금</span><div class="meta-right"><span class="status-dot" :class="{ pulse:running }"></span>{{running?'검토 진행 중':mode==='input'?'작성 중':'검토 완료'}}<span class="meta-date">2026. 10. 20</span></div></div>
    <section v-if="mode!=='input'" class="progress-panel"><div class="progress-title"><span class="success-ring">{{running?'◌':'✓'}}</span><strong>{{running?'광고 문안을 검토하고 있어요':'근거 확인까지, 검토가 완료되었어요'}}</strong><span>{{running?'예시 검토 진행 중':'5개 단계 완료'}}</span></div><div class="steps"><div v-for="(step,index) in steps" :key="step" class="step" :class="{complete:stage>index,current:stage===index}"><span class="step-circle">{{stage>index?'✓':String(index+1).padStart(2,'0')}}</span>{{step}}<span v-if="index<4" class="step-connector"></span></div></div></section>
    <div class="review-grid">
     <section class="panel source-panel"><div class="panel-heading"><div><span class="section-number">01</span><h2>광고 문안</h2></div><span class="muted">{{text.length}}자</span></div>
      <div class="source-tabs" v-if="mode!=='input'"><button :class="{active:tab==='original'}" @click="tab='original'">광고 원문</button><button :class="{active:tab==='revised'}" @click="tab='revised'">수정안 미리보기 <span class="mini-spark">✧</span></button></div>
      <div v-if="mode==='input'" class="input-area"><div class="input-label">검토할 광고 문안을 입력하세요<button @click="loadSample">예시 불러오기 ↗</button></div><textarea v-model="text" placeholder="제목, 금리, 가입 조건 등 실제 광고에 들어가는 문안을 붙여넣어 주세요." aria-label="광고 문안"></textarea></div>
      <div v-else class="ad-paper"><div class="paper-top"><span>AD COPY</span><span>{{tab==='original'?'원본':'수정 제안'}}</span></div><div class="ad-copy"><template v-for="(segment,index) in segments" :key="index"><button v-if="segment.id && tab==='original'" class="highlight" :class="[segment.id===4?'slate':'red',{focused:active===segment.id}]" @click="active=segment.id;filter='전체'">{{segment.text}}<sup>{{segment.id===4?'3':segment.id}}</sup></button><span v-else>{{segment.text}}</span></template></div><div class="paper-bottom"><span>레드은행 · 디지털 캠페인</span><span>TEXT</span></div></div>
      <div v-if="mode!=='input'" class="highlight-legend"><span><i class="red"></i>위반 소지</span><span><i class="slate"></i>사람 확인 필요</span><small>표시된 문구를 눌러 판정을 확인하세요</small></div>
      <div class="product-section"><div class="product-title"><h3>공시 대조 상품 <span>선택</span></h3><button v-if="mode==='input'" @click="picker=!picker">{{product?'변경':'상품 선택'}} ⌄</button><span v-else class="product-check">✓ {{product?'예시 공시 데이터':'공시 대조 미수행'}}</span></div><div v-if="picker && mode==='input'" class="product-picker"><input v-model="search" placeholder="은행명 또는 상품명 검색" aria-label="상품 검색"/><button v-for="p in matches" :key="p.id" @click="selected=p.id;picker=false">{{p.bank}} · {{p.name}}</button><p v-if="!matches.length">공시 상품을 찾지 못했습니다.</p><button @click="selected='';picker=false">상품 선택 건너뛰기</button></div><div v-if="product" class="product-box"><div class="bank-icon">R</div><div class="product-name"><small>{{product.bank}}</small><strong>{{product.name}}</strong></div><span class="tag">12개월</span></div><div v-if="product" class="rates"><div><span>기본 금리</span><strong>연 {{product.base}}<small>%</small></strong></div><div><span>최고 금리 <small>우대조건 충족 시</small></span><strong>연 {{product.max}}<small>%</small></strong></div></div><p class="product-footnote">{{product?'금리·상품명은 화면 구성을 위한 가상 데이터입니다.':'상품을 선택하지 않으면 공시 금리 대조를 건너뜁니다.'}}</p></div>
      <div v-if="mode==='input'" class="start-wrap"><button class="button primary" :disabled="!text.trim()" @click="start">✧ 예시 검토 시작 <span>→</span></button><p>입력 내용과 관계없이 준비된 예시 판정이 표시됩니다.</p></div>
     </section>
     <section class="results"><div class="results-heading"><div><span class="section-number">02</span><h2>검토 리포트</h2><span class="ai-label">AI 1차 의견</span></div><span class="muted">{{mode==='done'?available.length+'개 확인사항':'검토 대기'}}</span></div>
      <div v-if="mode==='input' || running" class="empty-state"><span class="empty-icon">{{running?'✧':'▧'}}</span><h3>{{running?steps[Math.min(stage,4)]+' 중입니다':'검토의 시작은, 광고 한 문장부터'}}</h3><p>{{running?'규정과 공시 정보를 대조하는 과정을 보여드립니다.':'왼쪽에 광고 문안을 입력하면 이곳에서\n문구별 판정과 수정 제안을 확인할 수 있어요.'}}</p><div class="empty-tags"><span>문구별 판정</span><span>근거 조문</span><span>수정 제안</span></div></div>
      <template v-else><div class="summary-cards"><button :class="{chosen:filter==='위반 소지'}" @click="filter=filter==='위반 소지'?'전체':'위반 소지'"><span><i class="dot red"></i>위반 소지</span><strong>{{product?2:1}}<small>건</small></strong><span class="summary-arrow">↗</span></button><button :class="{chosen:filter==='주의'}" @click="filter=filter==='주의'?'전체':'주의'"><span><i class="dot amber"></i>주의</span><strong>1<small>건</small></strong><span class="summary-arrow">↗</span></button><button :class="{chosen:filter==='사람 확인 필요'}" @click="filter=filter==='사람 확인 필요'?'전체':'사람 확인 필요'"><span><i class="dot slate"></i>사람 확인 필요</span><strong>1<small>건</small></strong><span class="summary-arrow">↗</span></button></div>
      <div class="results-toolbar"><button @click="filter='전체'" :class="{active:filter==='전체'}">{{filter==='전체'?'전체 판정':filter}} <span>{{visible.length}}</span></button><span>위험도 높은 순 ↓</span></div>
      <article v-for="issue in visible" :key="issue.id" class="verdict-card" :class="[issue.tone,{expanded:active===issue.id}]">
       <button class="verdict-top" @click="active=active===issue.id?null:issue.id"><span class="issue-index">{{String(issue.id).padStart(2,'0')}}</span><div><div class="verdict-badges"><span class="severity" :class="issue.tone">{{issue.level}}</span><span class="issue-type">{{issue.type}}</span><span v-if="feedback[issue.id]" class="feedback-done">✓ {{feedback[issue.id]}}</span></div><h3>{{issue.quote}}</h3></div><span class="expand-chevron">{{active===issue.id?'−':'＋'}}</span></button>
       <div v-if="active===issue.id" class="verdict-detail"><h4>{{issue.title}}</h4><p>{{issue.description}}</p><div v-if="issue.id===1 && product" class="comparison"><div><span>광고에 표시된 금리</span><strong class="red-text">연 4.5%</strong></div><span class="comparison-arrow">→</span><div><span>공시 최고 금리</span><strong>연 {{product.max}}%</strong></div><span class="difference">+0.7%p 차이</span></div><div class="evidence"><div class="evidence-title"><span>▥ {{issue.law || '근거 확인 실패'}}</span><span v-if="issue.evidence" class="verified">✓ 예시 근거</span></div><p>{{issue.evidence || '직접적인 근거를 확인하지 못해 담당자 검토가 필요합니다.'}}</p><div v-if="issue.evidence" class="evidence-meta">화면 표시용 요약 문구 · 실제 법령 인용 아님</div></div><div v-if="issue.fix" class="suggestion"><span>✧ 수정 제안</span><p>{{issue.fix}}</p></div><div class="card-actions"><span>이 판정에 대한 의견을 남겨주세요</span><button @click="rejectId=issue.id">기각</button><button class="agree" @click="agree(issue.id)">✓ 동의</button></div></div>
      </article><div class="review-notice"><span>ⓘ</span><p>AI의 1차 검토 의견입니다. 최종 심의는 담당자의 판단을 거쳐 확정해 주세요.</p></div></template>
     </section>
    </div><footer><span class="footer-brand">redpen.</span><span>명확한 근거가 만드는, 더 나은 금융광고.</span><span>프론트엔드 목업 · 실제 심의 미수행</span></footer>
   </div>
  </main>
  <div v-if="toast" class="toast" role="status">✓ {{toast}}</div>
  <div v-if="rejectId" class="modal-backdrop" @click.self="rejectId=null"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="reject-title"><h2 id="reject-title">판정 기각</h2><p>담당자의 검토 의견을 남겨주세요. 이 의견은 화면에서만 반영됩니다.</p><textarea v-model="reason" aria-label="기각 사유" placeholder="기각 사유를 입력하세요"></textarea><div><button class="button secondary" @click="rejectId=null">취소</button><button class="button primary" :disabled="!reason.trim()" @click="reject">기각 완료</button></div></section></div>
 </div>
</template>
