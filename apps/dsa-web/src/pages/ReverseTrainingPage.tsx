import { useState, useEffect, useCallback } from 'react';
import { reverseTrainingApi } from '../api/reverseTraining';
import type { HistoryPickItem, ReverseTrainingStatus, ScanResult, CompareResult } from '../api/reverseTraining';

const PAGE_SIZE = 20;

const fmtDate = (d: string) => { if (!d||d.length!==8) return d; return `${d.slice(0,4)}/${parseInt(d.slice(4,6))}/${parseInt(d.slice(6,8))}`; };
const fmtN = (v: number|null|undefined, d=2) => v!=null ? v.toFixed(d) : '-';
const fmtPct = (v: number|null|undefined) => v==null? '-' : <span className={v>=0?'text-danger':'text-success'}>{v>0?'+':''}{v.toFixed(2)}%</span>;
const fmtGain = (v: number|null|undefined) => { if(v==null)return'-'; if(v>0)return<span className="text-danger fw-bold">涨</span>; if(v<0)return<span className="text-success fw-bold">跌</span>; return '平'; };

// ---- 内联统计条（紧凑型） ----
function InlineStats({ status }: { status: ReverseTrainingStatus|null }) {
  if (!status) return null;
  return (
    <div className="d-flex flex-wrap align-items-center gap-3 mb-3 px-2 py-1 bg-light rounded small text-nowrap">
      <span><span className="text-muted">记录:</span> <strong>{status.historyCount}</strong> 条</span>
      <span className="text-muted">|</span>
      <span><span className="text-muted">成功率:</span> <strong className="text-success">{status.successRate.toFixed(1)}%</strong></span>
      <span className="text-muted">|</span>
      <span><span className="text-muted">成功/失败:</span> <strong>{status.successCount}</strong> / <span className="text-danger">{status.failCount}</span></span>
      <span className="text-muted">|</span>
      <span><span className="text-muted">个股数:</span> <strong>{status.uniqueStocks}</strong></span>
      <span className="text-muted">|</span>
      <span className="text-muted small">{fmtDate(status.dateRange?.start||'')} ~ {fmtDate(status.dateRange?.end||'')}</span>
    </div>
  );
}

// ---- 扫描结果 ----
function ScanPanel({ scan }: { scan: ScanResult|null }) {
  if (!scan) return null;
  return (
    <div className="card mb-3 border-primary">
      <div className="card-header py-1 px-2 bg-primary bg-opacity-10 d-flex justify-content-between align-items-center small">
        <strong>🔍 策略扫描结果</strong>
        <span className="text-muted">扫描 {scan.snapshotCount||0} 只 → 候选 {scan.afterFilterCount||0} 只，耗时 {scan.elapsedSeconds?.toFixed(1)||0}s</span>
      </div>
      <div className="table-responsive" style={{maxHeight:280}}>
        <table className="table table-sm table-striped mb-0 small">
          <thead className="table-light">
            <tr><th>#</th><th>代码</th><th>名称</th><th className="text-end">评分</th><th className="text-end">涨跌幅</th><th>趋势</th><th className="text-end">强度</th><th className="text-end">乖离</th><th>理由</th></tr>
          </thead>
          <tbody>
            {(scan.candidates||[]).map((c,i)=>(<tr key={i}><td>{i+1}</td><td className="fw-bold font-monospace">{c.code}</td><td>{c.name}</td><td className="text-end fw-bold">{c.score}</td><td className={`text-end fw-bold ${c.changePct>=0?'text-danger':'text-success'}`}>{c.changePct>0?'+':''}{c.changePct}%</td><td>{c.trendStatus}</td><td className="text-end">{c.trendStrength}</td><td className="text-end">{c.biasMa5?.toFixed(1)}%</td><td className="text-truncate" style={{maxWidth:180}}><small>{c.reason}</small></td></tr>))}
            {(!scan.candidates||scan.candidates.length===0)&&<tr><td colSpan={9} className="text-center text-muted py-2">无结果</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- 对比结果 ----
function ComparePanel({ compare }: { compare: CompareResult|null }) {
  if (!compare) return null;
  const rate = compare.matchRate||0;
  const rating = rate>=70 ? '🟢 优秀' : rate>=40 ? '🟡 良好' : '🔴 需优化';
  return (
    <div className="card mb-3 border-info">
      <div className="card-header py-1 px-2 bg-info bg-opacity-10 d-flex justify-content-between align-items-center small">
        <strong>📊 对比报告: {fmtDate(compare.date||'')}</strong>
        <span>匹配率 <strong>{rate.toFixed(1)}%</strong> ({compare.matchCount}/{compare.thirdParty?.length||0}) {rating}</span>
      </div>
      <div className="card-body py-2 small">
        <div className="row g-2">
          <div className="col-md-4">
            <div className="bg-light rounded p-2">
              <span className="text-muted">第三方 ({compare.thirdParty?.length||0}只)</span>
              <div className="d-flex flex-wrap gap-1 mt-1">
                {compare.thirdPartyDetail?.map((d,i)=>(<span key={i} className={`badge ${d.success===0?'bg-danger':'bg-success'}`}>{d.code}</span>))}
              </div>
            </div>
          </div>
          <div className="col-md-4">
            <div className="bg-light rounded p-2">
              <span className="text-muted">策略 ({compare.strategyPicks?.length||0}只)</span>
              <div className="d-flex flex-wrap gap-1 mt-1">{compare.strategyPicks?.map((c,i)=>(<span key={i} className="badge bg-primary">{c}</span>))}</div>
            </div>
          </div>
          <div className="col-md-4">
            <div className="bg-light rounded p-2">
              <span className="text-muted">匹配 ({compare.matches?.length||0}只)</span>
              <div className="d-flex flex-wrap gap-1 mt-1">
                {compare.matches?.map((c,i)=>(<span key={i} className="badge bg-warning text-dark">{c}</span>))}
                {compare.matches?.length===0&&<span className="text-muted">无</span>}
              </div>
            </div>
          </div>
        </div>
        {(compare.onlyThird?.length||0)>0&&<div className="mt-1 text-danger small">⚠ 第三方有策略没选: {compare.onlyThird?.map(d=>d.code).join(', ')}</div>}
        {(compare.onlyStrategy?.length||0)>0&&<div className="mt-1 text-primary small">策略有第三方没选: {compare.onlyStrategy?.map(d=>d.code).join(', ')}</div>}
      </div>
    </div>
  );
}

// ---- 主页面 ----
export default function ReverseTrainingPage() {
  const [status, setStatus] = useState<ReverseTrainingStatus|null>(null);
  const [records, setRecords] = useState<HistoryPickItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const [filterCode, setFilterCode] = useState('');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');

  const [showAdd, setShowAdd] = useState(false);
  const [addText, setAddText] = useState('');
  const [addMsg, setAddMsg] = useState('');

  const [editingId, setEditingId] = useState<number|null>(null);
  const [editForm, setEditForm] = useState<Partial<HistoryPickItem>>({});

  const [loading, setLoading] = useState('');
  const [scanResult, setScanResult] = useState<ScanResult|null>(null);
  const [compareResult, setCompareResult] = useState<CompareResult|null>(null);
  const [compareDate, setCompareDate] = useState('');
  const [trainMsg, setTrainMsg] = useState('');

  const fetchData = useCallback(async (p: number) => {
    try {
      const params: Record<string,unknown> = { page: p, pageSize: PAGE_SIZE };
      if (filterCode.trim()) params.stock_code = filterCode.trim();
      if (filterDateFrom) params.date_from = filterDateFrom.replace(/-/g,'');
      if (filterDateTo) params.date_to = filterDateTo.replace(/-/g,'');
      const [s, h] = await Promise.all([reverseTrainingApi.getStatus(), reverseTrainingApi.getHistory(params)]);
      setStatus(s); setRecords(h.items||[]); setTotal(h.total||0);
    } catch(e) { console.error(e); }
  }, [filterCode, filterDateFrom, filterDateTo]);

  useEffect(() => { document.title = '反向分析策略训练'; fetchData(1); }, [fetchData]);

  const goPage = (p: number) => { if (p>=1&&p<=totalPages) { setPage(p); fetchData(p); } };
  const doSearch = () => { setPage(1); fetchData(1); };
  const doReset = () => { setFilterCode(''); setFilterDateFrom(''); setFilterDateTo(''); setPage(1); };

  // Add
  const resetAddForm = () => { setAddText(''); setAddMsg(''); };
  const handleAdd = async () => {
    if (!addText.trim()) { setAddMsg('请粘贴股票数据'); return; }
    const lines = addText.trim().split('\n').map(l=>l.trim()).filter(Boolean);
    const picks: { stockCode:string; stockName:string; pickPrice:number|null; prevClose:number|null; pickDayChange:number|null; nextDayChange:number|null; success:number }[] = [];
    const dates: string[] = [];
    for (const line of lines) {
      const parts = line.split(/[\t]+/).map(p=>p.trim()).filter(Boolean);
      if (parts.length < 7) continue;
      const codeIdx = parts.findIndex(p=>/^\d{6}$/.test(p));
      if (codeIdx===-1||codeIdx+4>=parts.length) continue;
      const code = parts[codeIdx], name = parts[0]||'';
      const nums: number[] = [];
      for (let i=codeIdx+1;i<parts.length;i++){ const n=parseFloat(parts[i].replace(/[%,]/g,'')); if(!isNaN(n)&&nums.length<3)nums.push(n); }
      const datePart = parts.find(p=>/^\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}$/.test(p));
      if (datePart) { const d=new Date(datePart); if(!isNaN(d.getTime()))dates.push(`${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`); }
      picks.push({ stockCode:code, stockName:name, pickPrice:nums[0]||null, prevClose:nums[1]||null, pickDayChange:nums[2]||null, nextDayChange:nums[2]||null, success:parts[parts.length-1]==='跌'?0:1 });
    }
    if (picks.length===0) { setAddMsg('未识别到有效数据，格式：名称 代码 现价 昨日 涨跌幅 日期 隔日涨跌'); return; }
    if (!dates[0]||dates[0].length!==8) { setAddMsg('未识别到有效日期'); return; }
    try { await reverseTrainingApi.addPicks({ date: dates[0], picks }); resetAddForm(); setShowAdd(false); fetchData(page); } catch(e) { setAddMsg('保存失败: '+(e as Error).message); }
  };

  // Edit
  const startEdit = (item: HistoryPickItem) => { setEditingId(item.id); setEditForm({...item}); };
  const handleSaveEdit = async () => { if(!editingId)return; try{await reverseTrainingApi.updatePick(editingId,editForm);setEditingId(null);fetchData(page);}catch{alert('保存失败');} };
  const handleDelete = async (id:number) => { if(!window.confirm('确定删除？'))return; try{await reverseTrainingApi.deletePick(id);fetchData(page);}catch{alert('删除失败');} };

  // Actions
  const handleScan = async () => { setLoading('scanning'); try { const r=await reverseTrainingApi.runScan(5); setScanResult(r); } finally { setLoading(''); } };
  const handleCompare = async () => { setLoading('comparing'); try { const r=await reverseTrainingApi.runCompare(compareDate.replace(/-/g,'')||undefined); setCompareResult(r); } finally { setLoading(''); } };
  const handleTrain = async () => { setLoading('training');setTrainMsg('训练已启动...');try{const r=await reverseTrainingApi.runTrain();setTrainMsg(r.message);}catch(e){setTrainMsg('训练失败: '+(e as Error).message);}finally{setLoading('');} };

  return (
    <div className="container-fluid py-2">
      {/* Header */}
      <div className="d-flex align-items-center gap-1 mb-1">
        <h5 className="mb-0 me-2">📈 反向分析策略训练</h5>
        <button className="btn btn-sm btn-outline-primary" onClick={handleScan} disabled={!!loading}>{loading==='scanning'?'⏳ 扫描中':'🔍 扫描'}</button>
        <input type="date" className="form-control form-control-sm" style={{width:130}} value={compareDate} onChange={e=>setCompareDate(e.target.value)} title="对比日期"/>
        <button className="btn btn-sm btn-outline-info" onClick={handleCompare} disabled={!!loading}>{loading==='comparing'?'⏳ ...':'📊 对比'}</button>
        <button className="btn btn-sm btn-outline-success" onClick={handleTrain} disabled={!!loading}>{loading==='training'?'⏳ 训练':'🏋️ 训练'}</button>
      </div>
      <div className="mb-2">
        <button className="btn btn-sm btn-primary" onClick={()=>{resetAddForm();setShowAdd(!showAdd);}}>＋ 新增</button>
        {status && status.historyCount === 0 && (
          <button className="btn btn-sm btn-outline-warning ms-2" onClick={async()=>{try{await reverseTrainingApi.migrateFromCsv();fetchData(page);}catch(e){alert('初始化失败: '+(e as Error).message);}}}>🔄 初始化数据</button>
        )}
        {status && status.historyCount > 0 && (
          <span className="ms-2 text-muted small">✅ 数据已就绪</span>
        )}
        {showAdd && (
          <div className="card mt-2 border-primary">
            <div className="card-header bg-primary text-white py-1 px-2 d-flex justify-content-between align-items-center">
              <span className="small fw-bold">新增选股 — 从Excel粘贴</span>
              <button className="btn-close btn-close-white" style={{fontSize:'0.5rem'}} onClick={()=>setShowAdd(false)}/>
            </div>
            <div className="card-body py-2">
              <p className="text-muted small mb-1">格式：名称 ↑ 代码 ↑ 现价 ↑ 昨日 ↑ 涨跌幅 ↑ 日期 ↑ 隔日涨跌（自动识别）</p>
              <textarea className="form-control form-control-sm" rows={6} style={{fontFamily:'monospace',fontSize:'0.8rem'}} value={addText} onChange={e=>setAddText(e.target.value)} placeholder={"恒逸石化\t000703\t16.67\t15.18\t9.98%\t2026/6/25\t涨"+"\n京新药业\t002020\t11.78\t12.43\t2.82%\t2026/6/24\t涨"}/>
              <div className="d-flex align-items-center mt-2">
                <button className="btn btn-primary btn-sm me-2" onClick={handleAdd}>保存</button>
                <button className="btn btn-outline-secondary btn-sm" onClick={()=>setShowAdd(false)}>取消</button>
                {addMsg && <span className="ms-2 text-warning small">{addMsg}</span>}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Inline Stats */}
      <InlineStats status={status} />

      {trainMsg && <div className="alert alert-info py-1 px-2 mb-2 small">{trainMsg}</div>}

      <ScanPanel scan={scanResult} />
      <ComparePanel compare={compareResult} />

      {/* Search */}
      <div className="d-flex flex-wrap align-items-end gap-2 mb-2">
        <div><label className="form-label small mb-0">代码</label><input className="form-control form-control-sm" style={{width:90}} placeholder="600519" value={filterCode} onChange={e=>setFilterCode(e.target.value)} onKeyDown={e=>e.key==='Enter'&&doSearch()}/></div>
        <div><label className="form-label small mb-0">开始</label><input type="date" className="form-control form-control-sm" style={{width:140}} value={filterDateFrom} onChange={e=>setFilterDateFrom(e.target.value)}/></div>
        <div><label className="form-label small mb-0">结束</label><input type="date" className="form-control form-control-sm" style={{width:140}} value={filterDateTo} onChange={e=>setFilterDateTo(e.target.value)}/></div>
        <div><button className="btn btn-primary btn-sm" onClick={doSearch}>🔍 查询</button><button className="btn btn-outline-secondary btn-sm ms-1" onClick={doReset}>重置</button></div>
        <div className="ms-auto text-muted small align-self-center">共 <strong>{total}</strong> 条，第 {page}/{totalPages} 页</div>
      </div>

      {/* Table */}
      <div className="card shadow-sm">
        <div className="table-responsive">
          <table className="table table-striped table-hover table-sm align-middle mb-0 small">
            <thead className="table-dark">
              <tr>
                <th className="text-center" style={{width:35}}>#</th>
                <th>名称</th>
                <th className="text-center" style={{width:75}}>代码</th>
                <th className="text-end" style={{width:70}}>现价</th>
                <th className="text-end" style={{width:70}}>昨日</th>
                <th className="text-end" style={{width:75}}>涨跌幅</th>
                <th className="text-center" style={{width:95}}>甄选时间</th>
                <th className="text-center" style={{width:65}}>隔日</th>
                <th className="text-center" style={{width:90}}>操作</th>
              </tr>
            </thead>
            <tbody>
              {records.map((item,idx)=>(
                editingId===item.id ? (
                  <tr key={item.id} className="table-warning">
                    <td className="text-center text-muted">{(page-1)*PAGE_SIZE+idx+1}</td>
                    <td><input className="form-control form-control-sm" value={editForm.stockName||''} onChange={e=>setEditForm(f=>({...f,stockName:e.target.value}))}/></td>
                    <td className="text-center fw-bold">{item.stockCode}</td>
                    <td><input className="form-control form-control-sm text-end" type="number" step="0.01" value={editForm.pickPrice??''} onChange={e=>setEditForm(f=>({...f,pickPrice:e.target.value?+e.target.value:null}))}/></td>
                    <td><input className="form-control form-control-sm text-end" type="number" step="0.01" value={editForm.prevClose??''} onChange={e=>setEditForm(f=>({...f,prevClose:e.target.value?+e.target.value:null}))}/></td>
                    <td><input className="form-control form-control-sm text-end" type="number" step="0.01" value={editForm.pickDayChange??''} onChange={e=>setEditForm(f=>({...f,pickDayChange:e.target.value?+e.target.value:null}))}/></td>
                    <td className="text-center">{fmtDate(item.pickDate)}</td>
                    <td><input className="form-control form-control-sm text-end" type="number" step="0.01" value={editForm.nextDayChange??''} onChange={e=>setEditForm(f=>({...f,nextDayChange:e.target.value?+e.target.value:null}))}/></td>
                    <td className="text-center"><button className="btn btn-sm btn-success me-1 py-0" onClick={handleSaveEdit}>✓</button><button className="btn btn-sm btn-outline-secondary py-0" onClick={()=>setEditingId(null)}>✕</button></td>
                  </tr>
                ) : (
                  <tr key={item.id}>
                    <td className="text-center text-muted">{(page-1)*PAGE_SIZE+idx+1}</td>
                    <td>{item.stockName||<span className="text-muted">-</span>}</td>
                    <td className="text-center fw-bold font-monospace">{item.stockCode}</td>
                    <td className="text-end font-monospace">{fmtN(item.pickPrice)}</td>
                    <td className="text-end font-monospace">{fmtN(item.prevClose)}</td>
                    <td className="text-end font-monospace fw-bold">{fmtPct(item.pickDayChange)}</td>
                    <td className="text-center">{fmtDate(item.pickDate)}</td>
                    <td className="text-center">{fmtGain(item.nextDayChange)}</td>
                    <td className="text-center">
                      <button className="btn btn-sm btn-outline-primary me-1 py-0 px-1" onClick={()=>startEdit(item)}>编辑</button>
                      <button className="btn btn-sm btn-outline-danger py-0 px-1" onClick={()=>handleDelete(item.id)}>删除</button>
                    </td>
                  </tr>
                )
              ))}
              {records.length===0 && <tr><td colSpan={9} className="text-center py-4 text-muted">暂无数据，请先录入第三方选股记录</td></tr>}
            </tbody>
          </table>
        </div>
        {total>0 && (
          <div className="card-footer d-flex justify-content-center py-1">
            <div className="btn-group btn-group-sm">
              <button className="btn btn-outline-secondary" onClick={()=>goPage(1)} disabled={page===1}>««</button>
              <button className="btn btn-outline-secondary" onClick={()=>goPage(page-1)} disabled={page===1}>«</button>
              <span className="btn btn-outline-secondary disabled">{page}/{totalPages}</span>
              <button className="btn btn-outline-secondary" onClick={()=>goPage(page+1)} disabled={page===totalPages}>»</button>
              <button className="btn btn-outline-secondary" onClick={()=>goPage(totalPages)} disabled={page===totalPages}>»»</button>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
