import React, { useState, useEffect, useRef } from 'react';
import { 
  ShieldAlert, ShieldCheck, Shield, AlertTriangle, 
  CheckCircle, Info, Building2, Globe, FileText, 
  MapPin, Landmark, ArrowRight, Loader2, PlaySquare,
  Activity, FileSearch, ShieldX, Sun, Moon, ChevronLeft, ChevronRight, Home, History, Clock, Edit2, Trash2, Copy
} from 'lucide-react';
import { 
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, 
  CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar
} from 'recharts';
import ReactFlow, { Controls, Background, MarkerType, BaseEdge, getSmoothStepPath, Handle, Position } from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';

// --- Enums mimicking the Python backend ---
const Severity = {
  INFO: 'info',
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical'
};

const StepName = {
  SHAREHOLDERS: 'shareholders',
  KYB: 'kyb',
  SANCTIONS: 'sanctions',
  PROFILE: 'profile',
  LICENSES: 'licenses',
  FINANCES: 'finances',
  RESILIENCE: 'resilience',
  ESG: 'esg',
  MEDIA: 'media'
};

const SEVERITY_COLORS = {
  [Severity.INFO]: '#3b82f6',    // blue-500
  [Severity.LOW]: '#10b981',     // green-500
  [Severity.MEDIUM]: '#f59e0b',  // amber-500
  [Severity.HIGH]: '#ef4444',    // red-500
  [Severity.CRITICAL]: '#7f1d1d' // red-900
};

// --- Mock Backend Generator ---
// Simulates the A2A flow engine and final DDReport generation
const generateMockReport = (companyDetails) => {
  const isHighRisk = companyDetails.company_name.toLowerCase().includes('risk') || 
                     companyDetails.company_name.toLowerCase().includes('bad');

  const overall_risk = isHighRisk ? Severity.CRITICAL : Severity.MEDIUM;

  const red_flags = isHighRisk ? [
    { summary: "Major shareholder found on OFAC sanctions list.", severity: Severity.CRITICAL, is_red_flag: true, sources: [{ title: "OFAC SDN List", url: "https://ofac.treas.gov" }] },
    { summary: "Undisclosed debt of $50M to sanctioned entity.", severity: Severity.HIGH, is_red_flag: true, sources: [{ title: "Global Financial Registry" }] },
    { summary: "Severe ESG violation regarding supply chain labor.", severity: Severity.HIGH, is_red_flag: true, sources: [{ title: "Amnesty Int. Report" }] },
    { summary: "KYB records show shell company indicators.", severity: Severity.MEDIUM, is_red_flag: true, sources: [{ title: "Corporate Registry" }] }
  ] : [
    { summary: "Minor discrepancy in registered address vs website.", severity: Severity.LOW, is_red_flag: true, sources: [{ title: "Local Registry" }] },
    { summary: "Slightly elevated leverage ratio compared to industry avg.", severity: Severity.MEDIUM, is_red_flag: true, sources: [{ title: "Q3 Financials" }] }
  ];

  const strengths = isHighRisk ? [
    { summary: "Valid trading licenses in operating jurisdictions.", severity: Severity.INFO, is_strength: true, sources: [{ title: "License DB" }] }
  ] : [
    { summary: "Strong operational resilience with diversified supply chain.", severity: Severity.INFO, is_strength: true, sources: [{ title: "Supply Chain Audit" }] },
    { summary: "ISO 27001 Certified.", severity: Severity.INFO, is_strength: true, sources: [{ title: "ISO DB" }] },
    { summary: "Excellent ESG scores in environmental impact.", severity: Severity.INFO, is_strength: true, sources: [{ title: "ESG Global" }] }
  ];

  return {
    vendor_name: companyDetails.company_name || "Target Company",
    overall_risk,
    executive_summary: isHighRisk 
      ? `Critical risks identified for ${companyDetails.company_name}. A sanctioned entity was discovered deep in the ownership structure, triggering a deep-dive anomaly review. Furthermore, undisclosed debt and severe ESG violations represent unacceptable risk vectors.`
      : `Due diligence on ${companyDetails.company_name} reveals a generally stable vendor. A few minor discrepancies were noted in their operational profile, but strong resilience and healthy financials offset these. Medium overall risk is assigned purely due to industry baseline.`,
    recommendations: isHighRisk 
      ? ["Immediately halt onboarding process.", "Escalate OFAC hit to legal team.", "Request full disclosure of debt counterparties."]
      : ["Proceed with standard onboarding.", "Monitor address discrepancy in next review.", "Request updated Q4 financials for leverage check."],
    strengths,
    red_flags,
    sources: [...strengths, ...red_flags].flatMap(f => f.sources),
    step_risk_scores: isHighRisk
      ? { Ownership: 90, KYB: 50, Sanctions: 100, Profile: 25, Licenses: 0, Financials: 75, Resilience: 25, ESG: 75, Media: 50 }
      : { Ownership: 0, KYB: 0, Sanctions: 0, Profile: 0, Licenses: 0, Financials: 50, Resilience: 0, ESG: 0, Media: 25 },
    supply_items: [
      { supplier_name: "Global Materials Ltd", category: "Raw Materials", description: "Primary supplier of industrial-grade aluminium and copper alloys." },
      { supplier_name: "Logistics Pro", category: "Freight & Logistics", description: "Sole-source logistics partner for transpacific ocean freight." }
    ],
    supply_chain: [
      {
        vendor_name: "Global Materials Ltd",
        overall_risk: Severity.LOW,
        executive_summary: "Stable Tier-1 supplier.",
        red_flags: [],
        strengths: [],
        recommendations: [],
        supply_items: [
          { supplier_name: "Raw Metals Inc", category: "Mining & Metals", description: "Provides raw iron and copper inputs for materials manufacturing." }
        ],
        supply_chain: [
          {
            vendor_name: "Raw Metals Inc",
            overall_risk: Severity.MEDIUM,
            executive_summary: "Tier-2 supplier with moderate risk.",
            red_flags: [],
            strengths: [],
            recommendations: [],
            supply_chain: []
          }
        ]
      },
      {
        vendor_name: "Logistics Pro",
        overall_risk: Severity.HIGH,
        executive_summary: "High risk logistics provider with pending litigation.",
        red_flags: [],
        strengths: [],
        recommendations: [],
        supply_items: [
          { supplier_name: "Oceanic Shipping Shell", category: "Shipping", description: "Charter services for cargo routing." }
        ],
        supply_chain: [
          {
            vendor_name: "Oceanic Shipping Shell",
            overall_risk: Severity.CRITICAL,
            executive_summary: "Critical shell entity in logistics chain.",
            red_flags: [],
            strengths: [],
            recommendations: [],
            supply_chain: []
          }
        ]
      }
    ],
    generated_at: new Date().toISOString()
  };
};

// --- Components ---
export const getSeverityIcon = (sev) => {
  switch(sev) {
    case Severity.CRITICAL: return <ShieldX className="w-8 h-8 text-red-900 animate-pulse drop-shadow-md" />;
    case Severity.HIGH: return <ShieldAlert className="w-8 h-8 text-red-500" />;
    case Severity.MEDIUM: return <AlertTriangle className="w-8 h-8 text-amber-500" />;
    case Severity.LOW: return <CheckCircle className="w-8 h-8 text-green-500" />;
    default: return <Info className="w-8 h-8 text-blue-500" />;
  }
};


const InputForm = ({ onSubmit, onInstantMock }) => {
  const [formData, setFormData] = useState({
    company_name: '',
    registration_number: '',
    country: '',
    address: '',
    website: '',
    tax_id: '',
    use_mock: false,
    enable_supply_chain: false,
    tiers_to_search: 1,
    max_suppliers_per_node: 3,
    enable_parent_company: false,
    enable_parent_supply_chain: false
  });

  const handleChange = (e) => setFormData({ ...formData, [e.target.name]: e.target.value });

  return (
    <div className="max-w-2xl mx-auto bg-white dark:bg-slate-900 rounded-xl shadow-lg dark:shadow-slate-950/50 overflow-hidden border border-slate-200 dark:border-slate-800 transition-all duration-300">
      <div className="bg-slate-800 dark:bg-slate-950 p-6 text-white transition-colors duration-300">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <FileSearch className="w-6 h-6 text-blue-400" />
          New Vendor Due Diligence
        </h2>
        <p className="text-slate-300 mt-2 text-sm">Enter the company details below to initialize the multi-agent research workflow.</p>
      </div>
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Company Name *</label>
            <div className="relative">
              <Building2 className="w-4 h-4 absolute left-3 top-3 text-slate-400 dark:text-slate-500" />
              <input required name="company_name" value={formData.company_name} onChange={handleChange} className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Registration Number</label>
            <div className="relative">
              <FileText className="w-4 h-4 absolute left-3 top-3 text-slate-400 dark:text-slate-500" />
              <input name="registration_number" value={formData.registration_number} onChange={handleChange} className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Country</label>
            <div className="relative">
              <Globe className="w-4 h-4 absolute left-3 top-3 text-slate-400 dark:text-slate-500" />
              <input name="country" value={formData.country} onChange={handleChange} className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Tax ID</label>
            <div className="relative">
              <Landmark className="w-4 h-4 absolute left-3 top-3 text-slate-400 dark:text-slate-500" />
              <input name="tax_id" value={formData.tax_id} onChange={handleChange} className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition" />
            </div>
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Registered Address</label>
            <div className="relative">
              <MapPin className="w-4 h-4 absolute left-3 top-3 text-slate-400 dark:text-slate-500" />
              <input name="address" value={formData.address} onChange={handleChange} className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition" />
            </div>
          </div>
          <div className="md:col-span-2">
            <div className="flex items-center gap-2 mb-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input 
                  type="checkbox" 
                  name="enable_supply_chain" 
                  checked={formData.enable_supply_chain} 
                  onChange={(e) => setFormData({ ...formData, enable_supply_chain: e.target.checked })} 
                  className="w-5 h-5 text-blue-600 rounded border-slate-300 dark:border-slate-700 focus:ring-blue-500 bg-white dark:bg-slate-800 transition"
                />
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Research entire supply chain</span>
              </label>
            </div>
            {formData.enable_supply_chain && (
              <div className="flex items-center gap-6 mb-4 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-200 dark:border-slate-700">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Supply Chain Tiers to Search</label>
                  <input type="number" min="1" max="5" name="tiers_to_search" value={formData.tiers_to_search} onChange={handleChange} className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition rounded-lg" />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1">Max Suppliers Per Node</label>
                  <input type="number" min="1" max="10" name="max_suppliers_per_node" value={formData.max_suppliers_per_node} onChange={handleChange} className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:dark:ring-blue-500 outline-none transition rounded-lg" />
                </div>
              </div>
            )}
            <div className="flex items-center gap-2 mb-4 mt-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input 
                  type="checkbox" 
                  name="enable_parent_company" 
                  checked={formData.enable_parent_company} 
                  onChange={(e) => setFormData({ ...formData, enable_parent_company: e.target.checked })} 
                  className="w-5 h-5 text-blue-600 rounded border-slate-300 dark:border-slate-700 focus:ring-blue-500 bg-white dark:bg-slate-800 transition"
                />
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Research parent company</span>
              </label>
            </div>
            {formData.enable_parent_company && (
              <div className="flex items-center gap-2 mb-4 ml-6">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input 
                    type="checkbox" 
                    name="enable_parent_supply_chain" 
                    checked={formData.enable_parent_supply_chain} 
                    onChange={(e) => setFormData({ ...formData, enable_parent_supply_chain: e.target.checked })} 
                    className="w-5 h-5 text-blue-600 rounded border-slate-300 dark:border-slate-700 focus:ring-blue-500 bg-white dark:bg-slate-800 transition"
                  />
                  <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Research parent company's supply chain</span>
                </label>
              </div>
            )}
            <div className="flex items-center gap-2 mt-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input 
                  type="checkbox" 
                  name="use_mock" 
                  checked={formData.use_mock} 
                  onChange={(e) => setFormData({ ...formData, use_mock: e.target.checked })} 
                  className="w-5 h-5 text-blue-600 rounded border-slate-300 dark:border-slate-700 focus:ring-blue-500 bg-white dark:bg-slate-800 transition"
                />
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Use Mock Data Tools (Quick Examples)</span>
              </label>
              <div className="relative group cursor-help">
                <Info className="w-4 h-4 text-slate-400 hover:text-blue-500 transition-colors" />
                <div className="absolute left-0 bottom-full mb-2 w-64 p-2 bg-slate-800 text-slate-100 text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                  Tip: Include "Bad" or "Risk" in the company name to trigger a Supervisor Anomaly.
                  <div className="absolute left-4 top-full w-0 h-0 border-l-[6px] border-r-[6px] border-t-[6px] border-transparent border-t-slate-800"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="pt-4 flex justify-end">
          <button 
            type="button"
            onClick={() => onInstantMock(formData)}
            className="flex items-center gap-2 bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-800 dark:text-slate-100 px-6 py-3 rounded-lg font-semibold transition-all mr-4 shadow-sm"
          >
            Preview UI (Instant Mock)
          </button>
          <button 
            onClick={() => onSubmit(formData)}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold transition-all shadow-md shadow-blue-200 dark:shadow-blue-900/20"
          >
            Execute Pipeline
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};

const AGENT_LIST = ["shareholders", "kyb", "sanctions", "profile", "licenses", "finances", "resilience", "esg", "media"];

const LoadingGraphNode = ({ data }) => {
  return (
    <div className="bg-white dark:bg-slate-800 border-2 border-slate-300 dark:border-slate-600 rounded-lg p-3 shadow-md w-[260px] min-h-[110px] flex flex-col items-center justify-between">
      {/* Top handle: used by ownership lines (parent above, child below) */}
      <Handle type="target" position={Position.Top} id="top" className="opacity-0" />
      {/* Left handle: supplier connects from its left side to the target */}
      <Handle type="source" position={Position.Left} id="left" className="opacity-0" />
      {/* Bottom handle: used by ownership lines */}
      <Handle type="source" position={Position.Bottom} id="bottom" className="opacity-0" />
      {/* Right handle: supplied company receives on its right side */}
      <Handle type="target" position={Position.Right} id="right" className="opacity-0" />
      <div className="font-bold text-slate-800 dark:text-slate-100 mb-2 text-center w-full truncate" title={data.entity}>
        {data.entity}
      </div>
      <div className="grid grid-cols-3 gap-2 w-full mt-2">
        {AGENT_LIST.map(agent => {
          const status = data.agents[agent] || 'pending';
          let bgColor = 'bg-slate-200 dark:bg-slate-700';
          let ping = false;
          if (status === 'running') {
            bgColor = 'bg-blue-500';
            ping = true;
          } else if (status === 'completed') {
            bgColor = 'bg-green-500';
          } else if (status === 'error') {
            bgColor = 'bg-red-500';
          }
          return (
            <div key={agent} className="flex flex-col items-center gap-1" title={agent}>
              <div className="relative">
                {ping && <div className="absolute inset-0 rounded-full bg-blue-400 animate-ping opacity-75"></div>}
                <div className={`w-3 h-3 rounded-full ${bgColor} relative z-10`}></div>
              </div>
              <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-tighter w-full text-center">{agent}</span>
            </div>
          );
        })}
      </div>
      <Handle type="source" position={Position.Right} className="w-2 h-2" />
    </div>
  );
};

const loadingNodeTypes = { custom: LoadingGraphNode };

const ProcessingTerminal = ({ onComplete, onError, onCancel, companyDetails, resumeRunId }) => {
  const [logs, setLogs] = useState([]);
  const [nodeStates, setNodeStates] = useState({});
  const [isConsoleOpen, setIsConsoleOpen] = useState(false);
  const endOfLogsRef = useRef(null);
  const abortControllerRef = useRef(null);
  const jobIdRef = useRef(resumeRunId || Math.random().toString(36).substring(2, 15));
  const wsRef = useRef(null);
  const nodeStatesRef = useRef({});
  const entityMetaRef = useRef({}); // tracks { role, parentEntity } per entity
  
  useEffect(() => {
    endOfLogsRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);
  
  useEffect(() => {
    let isMounted = true;
    abortControllerRef.current = new AbortController();
    
    const runBackend = async () => {
      setLogs([{ text: `SYSTEM: ${resumeRunId ? 'Resuming' : 'Initializing'} DDContext for ${companyDetails.company_name}`, time: new Date().toLocaleTimeString() }]);
      setLogs(prev => [...prev, { text: "SYSTEM: Connecting to backend... (this may take a few minutes as agents process data)", time: new Date().toLocaleTimeString() }]);
      
      const jobId = jobIdRef.current;
      
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${wsProtocol}//${window.location.host}/api/ws/dd_status/${jobId}`);
      wsRef.current = ws;
      
      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data);
          if (data.logs && data.logs.length > 0) {
            setLogs(prev => [...prev, ...data.logs]);
            
            const newStates = { ...nodeStatesRef.current };
            const newMeta = { ...entityMetaRef.current };
            let stateChanged = false;
            for (const log of data.logs) {
              if (log.text.startsWith("[EVENT]")) {
                try {
                  const eventData = JSON.parse(log.text.substring(7));
                  const { entity, agent, status, role, parent_entity } = eventData;
                  if (!newStates[entity]) {
                    newStates[entity] = {};
                    stateChanged = true;
                  }
                  if (newStates[entity][agent] !== status) {
                    newStates[entity][agent] = status;
                    stateChanged = true;
                  }
                  // Track role metadata for graph positioning
                  if (!newMeta[entity]) {
                    newMeta[entity] = { role: role || 'root', parentEntity: parent_entity || null };
                    stateChanged = true;
                  }
                } catch (e) {}
              }
            }
            if (stateChanged) {
              nodeStatesRef.current = newStates;
              entityMetaRef.current = newMeta;
              setNodeStates(newStates);
            }
          }
        } catch (e) {
          console.error("WebSocket parse error:", e);
        }
      };
      
      try {
        let response;
        if (resumeRunId) {
          response = await fetch(`/api/dd_report/resume/${resumeRunId}`, {
            method: 'POST',
            signal: abortControllerRef.current.signal
          });
        } else {
          response = await fetch('/api/dd_report', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              company_name: companyDetails.company_name,
              registration_number: companyDetails.registration_number,
              country: companyDetails.country,
              address: companyDetails.address,
              website: companyDetails.website,
              tax_id: companyDetails.tax_id,
              use_mock: companyDetails.use_mock,
              tiers_to_search: companyDetails.enable_supply_chain ? (parseInt(companyDetails.tiers_to_search, 10) || 1) : 1,
              max_suppliers_per_node: companyDetails.enable_supply_chain ? (parseInt(companyDetails.max_suppliers_per_node, 10) || 3) : 3,
              enable_parent_company: companyDetails.enable_parent_company,
              enable_parent_supply_chain: companyDetails.enable_parent_supply_chain,
              job_id: jobId
            }),
            signal: abortControllerRef.current.signal
          });
        }
        
        if (!response.ok) {
           const errText = await response.text();
           throw new Error(`API Error: ${response.status} ${errText}`);
        }
        
        const reportData = await response.json();
        
        if (isMounted) {
          setLogs(prev => [...prev, { text: "SYSTEM: Pipeline Complete. Generating Report.", time: new Date().toLocaleTimeString() }]);
          setTimeout(() => {
            if (isMounted) onComplete(reportData, jobIdRef.current);
          }, 1000);
        }
      } catch (err) {
        if (err.name === 'AbortError') {
          if (isMounted) setLogs(prev => [...prev, { text: `SYSTEM: Flow interrupted by user.`, isError: true, time: new Date().toLocaleTimeString() }]);
          return;
        }
        if (isMounted) {
          setLogs(prev => [...prev, { text: `ERROR: ${err.message}`, isError: true, time: new Date().toLocaleTimeString() }]);
          setTimeout(() => {
            if (isMounted) onError(err.message);
          }, 3000);
        }
      }
    };
    
    runBackend();

    return () => {
      isMounted = false;
      if (wsRef.current) wsRef.current.close();
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run exactly once per mount

  const handleCancelClick = (discard = false) => {
    const msg = discard 
      ? "Are you sure you want to cancel and discard? All progress will be permanently lost."
      : "Are you sure you want to pause? You can resume this research run later from the sidebar.";
      
    if (window.confirm(msg)) {
      if (wsRef.current) wsRef.current.close();
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (jobIdRef.current) {
        fetch(`/api/dd_cancel/${jobIdRef.current}?discard=${discard}`, { method: 'POST' }).catch(() => {});
      }
      onCancel();
    }
  };

  // Build Graph — role-aware
  const nodes = [];
  const edges = [];
  const seenEdges = new Set();
  const entities = Object.keys(nodeStates);

  // Always ensure root node exists
  const rootName = companyDetails.company_name;
  const allEntities = entities.length === 0 ? [rootName] : entities;

  // Collect roles and parent relationships
  const roles = entityMetaRef.current;

  allEntities.forEach((entity) => {
    const role = roles[entity]?.role || (entity === rootName ? 'root' : 'supplier');
    const isRoot = entity === rootName;
    const isParent = role === 'parent';

    nodes.push({
      id: entity,
      type: 'custom',
      data: { entity, agents: nodeStates[entity] || {}, role },
      position: { x: 0, y: 0 },
    });

    const parentEntity = roles[entity]?.parentEntity;
    if (parentEntity && parentEntity !== entity) {
      const edgeId = isParent
        ? `${entity}-owns-${parentEntity}`
        : `${entity}-supplies-${parentEntity}`; // supplier→supplied: arrow points from entity to parentEntity
      if (!seenEdges.has(edgeId)) {
        seenEdges.add(edgeId);
        edges.push({
          id: edgeId,
          source: entity,
          target: parentEntity,
          sourceHandle: isParent ? 'bottom' : 'left',
          targetHandle: isParent ? 'top' : 'right',
          type: 'smoothstep',
          animated: true,
          style: { 
            stroke: isParent ? '#a855f7' : '#3b82f6', 
            strokeWidth: 2,
            strokeDasharray: isParent ? '6 3' : '4 4',
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: isParent ? '#a855f7' : '#3b82f6',
          }
        });
      }
    } else if (!isRoot && !parentEntity) {
      // Fallback: connect unknown entity to root
      const edgeId = `${entity}-supplies-${rootName}`;
      if (!seenEdges.has(edgeId)) {
        seenEdges.add(edgeId);
        edges.push({
          id: edgeId,
          source: entity,
          target: rootName,
          sourceHandle: 'left',
          targetHandle: 'right',
          type: 'smoothstep',
          animated: true,
          style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '4 4' },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: '#3b82f6',
          }
        });
      }
    }
  });

  // Pass ALL edges (including ownership) so getLayoutedElements can partition groups
  const { nodes: layoutedNodes } = getLayoutedElements(nodes, edges, 'LR');
  
  const layoutedEdges = edges;

  return (
    <div className="w-full flex flex-col h-[800px] bg-slate-50 dark:bg-slate-900 rounded-xl overflow-hidden shadow-2xl border border-slate-200 dark:border-slate-800 relative">
      {/* Header */}
      <div className="bg-slate-800 dark:bg-slate-950 px-4 py-3 flex items-center justify-between border-b border-slate-700 dark:border-slate-800 z-10 shrink-0">
        <div className="flex items-center gap-4">
          <span className="text-slate-300 font-bold flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-blue-400" /> Research in Progress...
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={() => setIsConsoleOpen(!isConsoleOpen)}
            className="text-sm bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1 rounded-md font-semibold transition border border-slate-600"
          >
            {isConsoleOpen ? 'Hide Debug' : 'Show Debug'}
          </button>
          <button 
            onClick={() => handleCancelClick(true)}
            className="text-sm bg-red-900/40 hover:bg-red-800/60 border border-red-800/50 text-red-400 px-3 py-1 rounded-md font-semibold transition"
          >
            Cancel & Discard
          </button>
          <button 
            onClick={() => handleCancelClick(false)}
            className="text-sm bg-amber-900/40 hover:bg-amber-800/60 border border-amber-800/50 text-amber-400 px-3 py-1 rounded-md font-semibold transition"
          >
            Pause & Save
          </button>
        </div>
      </div>
      
      {/* Split Body Container */}
      <div className="flex flex-1 overflow-hidden">
        
        {/* ReactFlow Graph Canvas */}
        <div className="flex-1 relative">
          <ReactFlow
            nodes={layoutedNodes}
            edges={layoutedEdges}
            nodeTypes={loadingNodeTypes}
            nodeOrigin={[0.5, 0.5]}
            minZoom={0.05}
            maxZoom={4}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            attributionPosition="bottom-left"
          >
            <Background color="#94a3b8" gap={20} />
            <Controls />
          </ReactFlow>
        </div>

        {/* Side Debug Console */}
        {isConsoleOpen && (
          <div className="w-1/3 bg-slate-950 border-l border-slate-700 flex flex-col">
            <div className="p-3 bg-slate-900 border-b border-slate-800 text-slate-400 font-mono text-xs flex justify-between shrink-0">
              <span>Terminal Output</span>
              <span>{logs.length} logs</span>
            </div>
            <div className="p-4 font-mono text-xs flex-1 overflow-y-auto space-y-2">
              {logs.map((log, i) => {
                if (log.text.startsWith("[EVENT]")) return null; // Hide structured events from raw log
                return (
                  <div key={i} className={`flex flex-col gap-1 ${log.isError ? 'text-red-400' : log.isSuper ? 'text-purple-400' : 'text-emerald-400'}`}>
                    <span className="text-slate-600 shrink-0 select-none">[{log.time}]</span>
                    <span className={`break-words ${log.isError ? 'font-bold' : ''}`}>{log.text}</span>
                  </div>
                );
              })}
              <div ref={endOfLogsRef} />
            </div>
          </div>
        )}
        
      </div>
    </div>
  );
};

const getLayoutedElements = (nodes, edges, direction = 'LR') => {
  const nodeWidth = 240; 
  const nodeHeight = 110;
  const PADDING = 40;

  const parentIds = new Set(edges.filter(e => e.id.includes('-owns-')).map(e => e.source));
  
  const groupAssignments = new Map();
  parentIds.forEach(parentId => {
    const groupId = `group-${parentId}`;
    groupAssignments.set(parentId, groupId);
    const queue = [parentId];
    while (queue.length > 0) {
      const current = queue.shift();
      edges.forEach(e => {
        if (e.target === current && e.id.includes('-supplies-')) {
          if (!groupAssignments.has(e.source)) {
            groupAssignments.set(e.source, groupId);
            queue.push(e.source);
          }
        }
      });
    }
  });

  const TARGET_GROUP = 'group-target';
  nodes.forEach(node => {
    if (!groupAssignments.has(node.id)) {
      groupAssignments.set(node.id, TARGET_GROUP);
    }
  });

  const groups = {
    [TARGET_GROUP]: { id: TARGET_GROUP, nodes: [], edges: [] }
  };
  parentIds.forEach(pid => {
    const gid = `group-${pid}`;
    groups[gid] = { id: gid, nodes: [], edges: [] };
  });

  nodes.forEach(node => {
    const gid = groupAssignments.get(node.id);
    groups[gid].nodes.push(node);
  });

  edges.forEach(edge => {
    if (edge.id.includes('-supplies-')) {
      const sourceGid = groupAssignments.get(edge.source);
      const targetGid = groupAssignments.get(edge.target);
      if (sourceGid && sourceGid === targetGid) {
        groups[sourceGid].edges.push(edge);
      }
    }
  });

  const childNodes = [];
  const parentNodes = [];
  const groupMetas = {};

  const groupIds = Object.keys(groups).filter(id => id !== TARGET_GROUP);
  groupIds.push(TARGET_GROUP);

  groupIds.forEach((gid) => {
    const group = groups[gid];
    if (group.nodes.length === 0) return;

    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({ rankdir: direction, ranksep: 140, nodesep: 80 });

    group.nodes.forEach(node => {
      dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
    });

    group.edges.forEach(edge => {
      if (gid === TARGET_GROUP) {
        dagreGraph.setEdge(edge.target, edge.source);
      } else {
        dagreGraph.setEdge(edge.source, edge.target);
      }
    });

    dagre.layout(dagreGraph);

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    group.nodes.forEach(node => {
      const pos = dagreGraph.node(node.id);
      if (pos.x < minX) minX = pos.x;
      if (pos.x > maxX) maxX = pos.x;
      if (pos.y < minY) minY = pos.y;
      if (pos.y > maxY) maxY = pos.y;
    });

    const trueMinX = minX - nodeWidth / 2 - PADDING;
    const trueMaxX = maxX + nodeWidth / 2 + PADDING;
    const trueMinY = minY - nodeHeight / 2 - PADDING;
    const trueMaxY = maxY + nodeHeight / 2 + PADDING;
    
    const groupWidth = trueMaxX - trueMinX;
    const groupHeight = trueMaxY - trueMinY;

    group.nodes.forEach(node => {
      const pos = dagreGraph.node(node.id);
      node.position = {
        x: pos.x - trueMinX,
        y: pos.y - trueMinY,
      };
      node.parentNode = gid;
      node.extent = 'parent';
      node.origin = [0.5, 0.5]; // Centers the node on the coordinate
      // We do not push to childNodes here because we'll do it later from groups
    });

    groupMetas[gid] = {
      width: groupWidth,
      height: groupHeight
    };
  });

  const placedGroups = {
    [TARGET_GROUP]: { x: 0, y: 0 }
  };
  
  if (groupMetas[TARGET_GROUP]) {
    parentNodes.push({
      id: TARGET_GROUP,
      type: 'group',
      position: { x: 0, y: 0 },
      style: {
        width: groupMetas[TARGET_GROUP].width,
        height: groupMetas[TARGET_GROUP].height,
        backgroundColor: 'rgba(241, 245, 249, 0.2)',
        border: '2px dashed rgba(148, 163, 184, 0.4)',
        borderRadius: '16px',
        zIndex: -1,
        pointerEvents: 'none'
      }
    });
  }

  let currentXOffset = groupMetas[TARGET_GROUP] ? - (groupMetas[TARGET_GROUP].width / 2 + 100) : 0;

  const ownsEdges = edges.filter(e => e.id.includes('-owns-'));
  
  ownsEdges.forEach(edge => {
    const parentId = edge.source;
    const subsidId = edge.target;
    const gid = `group-${parentId}`;
    
    if (groupMetas[gid]) {
      // Find nodes from the dagre layout directly
      const subsidGroupNodes = groups[groupAssignments.get(subsidId)]?.nodes || [];
      const subsidNode = subsidGroupNodes.find(n => n.id === subsidId);
      const parentGroupNodes = groups[gid]?.nodes || [];
      const parentNode = parentGroupNodes.find(n => n.id === parentId);
      
      if (parentNode && subsidNode) {
        const subsidGroupGid = subsidNode.parentNode;
        const subsidGroupCoords = placedGroups[subsidGroupGid] || { x: 0, y: 0 };
        const subsidGroupMeta = groupMetas[subsidGroupGid];
        
        const globalSubsidY = subsidGroupCoords.y - subsidGroupMeta.height/2 + subsidNode.position.y;
        
        const parentGroupHeight = groupMetas[gid].height;
        const parentLocalY = parentNode.position.y;
        
        const parentGroupY = globalSubsidY - parentLocalY + parentGroupHeight/2;
        
        const parentGroupWidth = groupMetas[gid].width;
        const parentGroupX = currentXOffset - parentGroupWidth/2;
        
        placedGroups[gid] = { x: parentGroupX, y: parentGroupY };
        
        parentNodes.push({
          id: gid,
          type: 'group',
          position: { x: parentGroupX, y: parentGroupY },
          style: {
            width: parentGroupWidth,
            height: parentGroupHeight,
            backgroundColor: 'rgba(241, 245, 249, 0.2)',
            border: '2px dashed rgba(148, 163, 184, 0.4)',
            borderRadius: '16px',
            zIndex: -1,
            pointerEvents: 'none'
          }
        });
        
        currentXOffset = parentGroupX - parentGroupWidth/2 - 100;
      }
    }
  });

  // Now populate childNodes
  groupIds.forEach((gid) => {
    const group = groups[gid];
    if (group.nodes.length === 0) return;
    
    group.nodes.forEach(node => {
      childNodes.push(node);
    });
  });

  const finalNodes = [...parentNodes, ...childNodes];

  return { nodes: finalNodes, edges };
};

const CustomNode = ({ data }) => {
  return (
    <div className="bg-white dark:bg-slate-800 border-2 rounded-lg p-3 shadow-md w-[220px] min-h-[110px] flex flex-col items-center justify-between transition-all hover:shadow-lg hover:-translate-y-1 relative" style={{borderColor: data.color}}>
      {data.isShared && (
        <div className="absolute -top-3 -right-3 bg-amber-100 text-amber-800 dark:bg-amber-900/80 dark:text-amber-300 border border-amber-300 dark:border-amber-700 text-[9px] font-bold px-2 py-0.5 rounded-full shadow-sm flex items-center gap-1 z-10" title="This supplier also supplies another group in this network">
          <Copy className="w-3 h-3" /> Shared
        </div>
      )}
      {/* Top handles */}
      <Handle type="target" position={Position.Top} id="top-target" className="opacity-0" />
      <Handle type="source" position={Position.Top} id="top-source" className="opacity-0" />
      {/* Left handles */}
      <Handle type="source" position={Position.Left} id="left-source" className="opacity-0" />
      <Handle type="target" position={Position.Left} id="left-target" className="opacity-0" />
      <div className="flex flex-col items-center gap-1 mb-2 w-full">
        {data.icon}
        <span className="font-bold text-slate-800 dark:text-slate-100 text-sm text-center line-clamp-2 w-full">{data.label}</span>
      </div>
      <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border`} style={{color: data.color, borderColor: data.color}}>
        {data.risk} Risk
      </span>
      {/* Bottom handles */}
      <Handle type="source" position={Position.Bottom} id="bottom-source" className="opacity-0" />
      <Handle type="target" position={Position.Bottom} id="bottom-target" className="opacity-0" />
      {/* Right handles */}
      <Handle type="target" position={Position.Right} id="right-target" className="opacity-0" />
      <Handle type="source" position={Position.Right} id="right-source" className="opacity-0" />
    </div>
  );
};
const nodeTypes = { custom: CustomNode };

const SupplyChainGraph = ({ report, theme, onNodeSelect }) => {
  const [isLegendOpen, setIsLegendOpen] = useState(true);
  const initialNodes = [];
  const initialEdges = [];
  const seenNodes = new Set();
  const seenEdges = new Set();

  // Track all raw vendor names to detect shared suppliers
  const vendorCounts = new Map();
  const countVendors = (node) => {
    vendorCounts.set(node.vendor_name, (vendorCounts.get(node.vendor_name) || 0) + 1);
    if (node.supply_chain && node.supply_chain.length > 0) {
      node.supply_chain.forEach(child => countVendors(child));
    }
    if (node.parent_company) {
      countVendors(node.parent_company);
    }
  };
  countVendors(report);

  // Build supply chain edges
  const buildGraph = (node, parentId = null, relationship = 'supply', branch = 'target') => {
    const rawNodeId = node.vendor_name;
    const nodeId = parentId ? `${branch}-${rawNodeId}` : rawNodeId;
    const isShared = vendorCounts.get(rawNodeId) > 1 && relationship === 'supply';

    if (!seenNodes.has(nodeId)) {
      seenNodes.add(nodeId);
      initialNodes.push({
        id: nodeId,
        type: 'custom',
        data: {
          label: rawNodeId,
          risk: node.overall_risk,
          color: SEVERITY_COLORS[node.overall_risk],
          icon: getSeverityIcon(node.overall_risk),
          fullReport: node,
          relationship,
          isShared,
        },
        position: { x: 0, y: 0 },
      });
    }

    if (parentId) {
      const isParentRel = relationship === 'parent';
      const edgeId = isParentRel
        ? `${nodeId}-owns-${parentId}`
        : `${nodeId}-supplies-${parentId}`; // supplier→supplied: arrow points from nodeId to parentId

      if (!seenEdges.has(edgeId)) {
        seenEdges.add(edgeId);
        
        let sourceHandleId, targetHandleId;
        if (branch === 'target') {
          sourceHandleId = 'left-source';
          targetHandleId = 'right-target';
        } else {
          sourceHandleId = 'right-source';
          targetHandleId = 'left-target';
        }
        
        initialEdges.push({
          id: edgeId,
          source: nodeId,
          target: parentId,
          sourceHandle: sourceHandleId,
          targetHandle: targetHandleId,
          type: 'smoothstep',
          animated: true,
          // No labels — relationship shown in legend
          style: {
            stroke: isParentRel
              ? (theme === 'dark' ? '#a855f7' : '#9333ea')
              : (theme === 'dark' ? '#3b82f6' : '#2563eb'),
            strokeWidth: 2,
            strokeDasharray: isParentRel ? '6 3' : '4 4',
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: isParentRel
              ? (theme === 'dark' ? '#a855f7' : '#9333ea')
              : (theme === 'dark' ? '#3b82f6' : '#2563eb'),
          },
        });
      }
    }

    // Supply chain nodes inherit the current branch
    if (node.supply_chain && node.supply_chain.length > 0) {
      node.supply_chain.forEach(child => buildGraph(child, nodeId, 'supply', branch));
    }

    // Parent company starts its own distinct 'parent' branch
    if (node.parent_company) {
      buildGraph(node.parent_company, nodeId, 'parent', 'parent');
    }
  };

  buildGraph(report);

  // Pass ALL initialEdges (including ownership) to support ReactFlow Group Node partitioning
  const { nodes: layoutedNodes } = getLayoutedElements(initialNodes, initialEdges, 'LR');
  
  const layoutedEdges = initialEdges;

  const onNodeClick = (event, node) => {
    if (onNodeSelect) {
      onNodeSelect(node.data.fullReport);
    }
  };

  return (
    <div className="h-full w-full bg-slate-50 dark:bg-slate-900/50 relative">
      <ReactFlow
        nodes={layoutedNodes}
        edges={layoutedEdges}
        nodeTypes={nodeTypes}
        nodeOrigin={[0.5, 0.5]}
        minZoom={0.05}
        maxZoom={4}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        className={theme === 'dark' ? 'dark' : ''}
      >
        <Background color={theme === 'dark' ? '#334155' : '#cbd5e1'} gap={16} />
        <Controls />
        
        {/* Legend Panel */}
        <div className="absolute bottom-4 right-4 bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm p-3 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 text-xs z-10 transition-all duration-300 overflow-hidden w-44">
          <div className="flex items-center justify-between gap-4 cursor-pointer group" onClick={() => setIsLegendOpen(!isLegendOpen)}>
            <h4 className="font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider select-none">Legend</h4>
            <button className="text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-200 transition-colors" title={isLegendOpen ? 'Collapse' : 'Expand'}>
              {isLegendOpen ? <ChevronRight className="w-4 h-4 rotate-90" /> : <ChevronRight className="w-4 h-4 -rotate-90" />}
            </button>
          </div>
          {isLegendOpen && (
            <div className="mt-3 space-y-3">
              {/* Risk sub-section */}
              <div>
                <p className="text-[10px] uppercase tracking-widest text-slate-400 dark:text-slate-500 font-bold mb-1.5">Risk</p>
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-blue-500"></div><span className="text-slate-600 dark:text-slate-300">No Risk</span></div>
                  <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-green-500"></div><span className="text-slate-600 dark:text-slate-300">Low</span></div>
                  <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-amber-500"></div><span className="text-slate-600 dark:text-slate-300">Medium</span></div>
                  <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-red-500"></div><span className="text-slate-600 dark:text-slate-300">High</span></div>
                  <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-red-900 animate-pulse"></div><span className="text-slate-600 dark:text-slate-300">Critical</span></div>
                </div>
              </div>
              {/* Relationship sub-section */}
              <div className="border-t border-slate-200 dark:border-slate-700 pt-3">
                <p className="text-[10px] uppercase tracking-widest text-slate-400 dark:text-slate-500 font-bold mb-1.5">Relationship</p>
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-0 flex-shrink-0" style={{borderTop:'2px dashed #3b82f6',position:'relative'}}>
                    </div>
                    <span className="text-slate-600 dark:text-slate-300">Supplies</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-0 flex-shrink-0" style={{borderTop:'2px dashed #9333ea',position:'relative'}}>
                    </div>
                    <span className="text-slate-600 dark:text-slate-300">Owns</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </ReactFlow>
    </div>
  );
};

const SupplyInputsSection = ({ supplyItems }) => {
  if (!supplyItems || supplyItems.length === 0) return null;

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm p-6 transition-all duration-300">
      <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100 border-b border-slate-200 dark:border-slate-800 pb-2 flex items-center gap-2 mb-4">
        <Building2 className="w-5 h-5 text-blue-600 dark:text-blue-500" />
        Supply Inputs (Tier-1 Suppliers)
      </h3>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead>
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Supplier Name</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Category</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800 bg-transparent">
            {supplyItems.map((item, index) => (
              <tr key={index} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors duration-150">
                <td className="px-4 py-3.5 whitespace-nowrap text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {item.supplier_name}
                </td>
                <td className="px-4 py-3.5 whitespace-nowrap">
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 border border-blue-100 dark:border-blue-900/50">
                    {item.category}
                  </span>
                </td>
                <td className="px-4 py-3.5 text-sm text-slate-600 dark:text-slate-300 max-w-md break-words">
                  {item.description}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const Dashboard = ({ report, rootReport, onReset, onResetSupplier, theme, isGraphOpen, onToggleGraph, jobId }) => {
  // Data prep for charts
  const severityCounts = report.red_flags.reduce((acc, flag) => {
    acc[flag.severity] = (acc[flag.severity] || 0) + 1;
    return acc;
  }, {});
  
  const pieData = Object.entries(severityCounts).map(([key, val]) => ({
    name: key.toUpperCase(),
    value: val,
    color: SEVERITY_COLORS[key]
  }));

  const radarSteps = ['Ownership', 'KYB', 'Sanctions', 'Profile', 'Licenses', 'Financials', 'Resilience', 'ESG', 'Media'];
  const radarData = radarSteps.map(subject => ({
    subject,
    A: (report.step_risk_scores && report.step_risk_scores[subject] != null) 
      ? report.step_risk_scores[subject] 
      : 0,
    fullMark: 100
  }));

  const redFlagsByCategory = report.red_flags.reduce((acc, flag) => {
    const cat = flag.category || 'Other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(flag);
    return acc;
  }, {});

  const strengthsByCategory = report.strengths.reduce((acc, flag) => {
    const cat = flag.category || 'Other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(flag);
    return acc;
  }, {});

  const handleDownloadAuditLog = () => {
    if (!report.audit_log) return;
    const blob = new Blob([report.audit_log], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_log_${report.vendor_name.replace(/\s+/g, '_')}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="w-full max-w-full mx-auto space-y-6 pb-12">
      {/* Header Area */}
      <div className="flex flex-col items-start gap-4 bg-white dark:bg-slate-900 p-6 rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 transition-all duration-300 w-full overflow-hidden">
        <div className="w-full">
          {rootReport && rootReport.vendor_name !== report.vendor_name && (
            <div className="flex items-center gap-2 mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400 flex-wrap">
              <button onClick={onResetSupplier} className="hover:text-blue-500 transition-colors flex items-center gap-1 shrink-0">
                <Home className="w-4 h-4" />
                <span className="truncate max-w-[150px] sm:max-w-xs">{rootReport.vendor_name}</span>
              </button>
              <ChevronRight className="w-4 h-4 shrink-0" />
              <span className="text-slate-800 dark:text-slate-200 break-words">{report.vendor_name}</span>
            </div>
          )}
          <h1 className="text-3xl font-bold text-slate-800 dark:text-slate-100 flex items-center gap-3 break-words">
            {report.vendor_name}
          </h1>
          <p className="text-slate-500 dark:text-slate-400 mt-2">Generated: {new Date(report.generated_at).toLocaleString()}</p>
        </div>

        <div className="flex flex-col sm:flex-row justify-between w-full gap-4 items-start sm:items-center border-t border-slate-200 dark:border-slate-800 pt-5">
          <div className="flex flex-col items-start">
            <span className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">Overall Risk</span>
            <div className="flex items-center gap-2">
              {getSeverityIcon(report.overall_risk)}
              <span className={`text-2xl font-bold uppercase`} style={{color: SEVERITY_COLORS[report.overall_risk]}}>
                {report.overall_risk}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 justify-end">
            {rootReport && ((rootReport.supply_chain && rootReport.supply_chain.length > 0) || rootReport.parent_company) && onToggleGraph && (
              <button
                onClick={onToggleGraph}
                className="flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg text-sm font-semibold transition border border-slate-200 dark:border-slate-700 shadow-sm"
                title={isGraphOpen ? "Hide Relationship Graph" : "Show Relationship Graph"}
              >
                <Activity className="w-4 h-4" />
                {isGraphOpen ? 'Hide Relationship Graph' : 'Show Relationship Graph'}
              </button>
            )}
            {report.audit_log && (
              <button onClick={handleDownloadAuditLog} className="flex items-center gap-2 px-4 py-2 bg-blue-100 hover:bg-blue-200 dark:bg-blue-900/50 dark:hover:bg-blue-800/50 text-blue-700 dark:text-blue-300 rounded-lg text-sm font-semibold transition border border-blue-200 dark:border-blue-800 shadow-sm">
                <FileText className="w-4 h-4" />
                Audit Log
              </button>
            )}
            {jobId && (
              <button onClick={() => window.open(`/api/history/${jobId}/pdf`, '_blank')} className="flex items-center gap-2 px-4 py-2 bg-rose-100 hover:bg-rose-200 dark:bg-rose-900/50 dark:hover:bg-rose-800/50 text-rose-700 dark:text-rose-300 rounded-lg text-sm font-semibold transition border border-rose-200 dark:border-rose-800 shadow-sm">
                <FileText className="w-4 h-4" />
                Export PDF
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Exec Summary */}
      <div className="bg-slate-800 dark:bg-slate-900/50 dark:border dark:border-slate-800 text-white p-6 rounded-xl shadow-sm transition-all duration-300">
        <h2 className="text-lg font-semibold text-slate-300 dark:text-slate-400 uppercase tracking-wider mb-3">Executive Summary</h2>
        <p className="text-lg leading-relaxed text-slate-100">{report.executive_summary}</p>
      </div>

      {/* Supply Inputs */}
      {report.has_identifiable_third_party_suppliers !== false && report.supply_items && report.supply_items.length > 0 && (
        <SupplyInputsSection supplyItems={report.supply_items} />
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-slate-900 p-6 rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 transition-all duration-300">
          <h3 className="text-base font-bold text-slate-800 dark:text-slate-200 mb-4 text-center">Red Flags by Severity</h3>
          <div className="h-64">
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value" isAnimationActive={false}>
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <RechartsTooltip 
                    contentStyle={{
                      backgroundColor: theme === 'dark' ? '#1e293b' : '#ffffff',
                      borderColor: theme === 'dark' ? '#334155' : '#e2e8f0',
                      color: theme === 'dark' ? '#f8fafc' : '#0f172a',
                      borderRadius: '8px'
                    }}
                  />
                  <Legend formatter={(value) => <span className="text-slate-600 dark:text-slate-300 text-sm font-semibold">{value}</span>} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400 dark:text-slate-500">No Red Flags Detected</div>
            )}
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-6 rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 transition-all duration-300">
          <h3 className="text-base font-bold text-slate-800 dark:text-slate-200 mb-4 text-center">Risk Vector Analysis</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                <PolarGrid stroke={theme === 'dark' ? '#334155' : '#e2e8f0'} />
                <PolarAngleAxis dataKey="subject" tick={{fill: theme === 'dark' ? '#94a3b8' : '#64748b', fontSize: 12}} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} stroke={theme === 'dark' ? '#334155' : '#e2e8f0'} />
                <Radar name="Risk Score" dataKey="A" stroke="#3b82f6" fill="#3b82f6" fillOpacity={theme === 'dark' ? 0.35 : 0.5} isAnimationActive={false} />
                <RechartsTooltip 
                  contentStyle={{
                    backgroundColor: theme === 'dark' ? '#1e293b' : '#ffffff',
                    borderColor: theme === 'dark' ? '#334155' : '#e2e8f0',
                    color: theme === 'dark' ? '#f8fafc' : '#0f172a',
                    borderRadius: '8px'
                  }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Details Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Red Flags */}
        <div className="space-y-4">
          <h3 className="text-xl font-bold text-slate-800 dark:text-slate-100 border-b border-slate-200 dark:border-slate-800 pb-2 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            Red Flags
          </h3>
          {Object.entries(redFlagsByCategory).length === 0 ? (
            <p className="text-slate-500 dark:text-slate-400 italic">No red flags identified.</p>
          ) : (
            Object.entries(redFlagsByCategory)
              .sort(([catA], [catB]) => {
                const idxA = AGENT_LIST.indexOf(catA.toLowerCase());
                const idxB = AGENT_LIST.indexOf(catB.toLowerCase());
                return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
              })
              .map(([category, flags]) => (
              <div key={category} className="mb-4">
                <h4 className="text-md font-bold text-slate-700 dark:text-slate-300 mb-3 ml-1 uppercase tracking-wider">{category}</h4>
                <div className="space-y-3">
                  {flags.map((flag, idx) => (
                    <div key={idx} className="bg-red-50 dark:bg-red-950/20 p-4 rounded-lg border border-red-100 dark:border-red-900/30 flex gap-4 items-start">
                      <div className="shrink-0 mt-1">
                        {flag.severity === Severity.CRITICAL ? <ShieldX className="w-5 h-5 text-red-800 dark:text-red-400" /> : <ShieldAlert className="w-5 h-5 text-red-500 dark:text-red-400" />}
                      </div>
                      <div className="flex-1">
                        <span className="text-xs font-bold uppercase tracking-wider px-2 py-1 rounded bg-white dark:bg-slate-800 text-red-700 dark:text-red-400 shadow-sm border border-red-100/50 dark:border-red-900/20 mb-2 inline-block">
                          {flag.severity}
                        </span>
                        <p className="text-slate-800 dark:text-slate-200">{flag.summary}</p>
                        <div className="mt-3 flex flex-col gap-1.5">
                          {flag.sources && flag.sources.map((src, i) => (
                            <div key={i} className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5 flex-wrap">
                              <FileText className="w-3 h-3" />
                              <span className="font-semibold">Source:</span>
                              {src.url ? (
                                <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">
                                  {src.title}
                                </a>
                              ) : (
                                <span>{src.title}</span>
                              )}
                              {src.is_database && (
                                <span className="ml-1 px-1.5 py-0.5 bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-400 rounded text-[10px] uppercase font-bold tracking-wider">
                                  Database API
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Strengths & Recs */}
        <div className="space-y-6">
          <div>
            <h3 className="text-xl font-bold text-slate-800 dark:text-slate-100 border-b border-slate-200 dark:border-slate-800 pb-2 flex items-center gap-2 mb-4">
              <CheckCircle className="w-5 h-5 text-green-500" />
              Verified Strengths
            </h3>
            <div className="space-y-4">
              {Object.entries(strengthsByCategory).length === 0 ? (
                <p className="text-slate-500 dark:text-slate-400 italic">No verified strengths identified.</p>
              ) : (
                Object.entries(strengthsByCategory)
                  .sort(([catA], [catB]) => {
                    const idxA = AGENT_LIST.indexOf(catA.toLowerCase());
                    const idxB = AGENT_LIST.indexOf(catB.toLowerCase());
                    return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
                  })
                  .map(([category, flags]) => (
                  <div key={category}>
                    <h4 className="text-md font-bold text-slate-700 dark:text-slate-300 mb-2 ml-1 uppercase tracking-wider">{category}</h4>
                    <div className="space-y-3">
                      {flags.map((str, idx) => (
                        <div key={idx} className="bg-emerald-50 dark:bg-emerald-950/20 p-4 rounded-lg border border-emerald-100 dark:border-emerald-900/30 flex gap-3 items-start">
                          <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                          <div className="flex-1">
                            <p className="text-slate-700 dark:text-slate-300 text-sm">{str.summary}</p>
                            <div className="mt-3 flex flex-col gap-1.5">
                              {str.sources && str.sources.map((src, i) => (
                                <div key={i} className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5 flex-wrap">
                                  <FileText className="w-3 h-3" />
                                  <span className="font-semibold">Source:</span>
                                  {src.url ? (
                                    <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-emerald-600 dark:text-emerald-400 hover:underline">
                                      {src.title}
                                    </a>
                                  ) : (
                                    <span>{src.title}</span>
                                  )}
                                  {src.is_database && (
                                    <span className="ml-1 px-1.5 py-0.5 bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-400 rounded text-[10px] uppercase font-bold tracking-wider">
                                      Database API
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div>
            <h3 className="text-xl font-bold text-slate-800 dark:text-slate-100 border-b border-slate-200 dark:border-slate-800 pb-2 flex items-center gap-2 mb-4">
              <Activity className="w-5 h-5 text-blue-500" />
              Recommendations
            </h3>
            <ul className="space-y-2">
              {report.recommendations.map((rec, idx) => (
                <li key={idx} className="flex gap-3 items-start">
                  <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 text-sm font-bold shrink-0">
                    {idx + 1}
                  </span>
                  <p className="text-slate-700 dark:text-slate-300 mt-0.5">{rec}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};


export default function App() {
  const [view, setView] = useState('input'); // 'input' | 'processing' | 'dashboard'
  const [companyDetails, setCompanyDetails] = useState(null);
  const [report, setReport] = useState(null);
  const [globalError, setGlobalError] = useState(null);
  const [isGraphOpen, setIsGraphOpen] = useState(false);
  const [currentJobId, setCurrentJobId] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [historyList, setHistoryList] = useState([]);
  const [interruptedRuns, setInterruptedRuns] = useState([]);
  const [resumeRunId, setResumeRunId] = useState(null);
  const [activeSidebarTab, setActiveSidebarTab] = useState('history');
  const [isEditingHistory, setIsEditingHistory] = useState(false);
  const [selectedHistoryItems, setSelectedHistoryItems] = useState(new Set());
  const [isEditingInterrupted, setIsEditingInterrupted] = useState(false);
  const [selectedInterruptedItems, setSelectedInterruptedItems] = useState(new Set());
  const [selectedSupplier, setSelectedSupplier] = useState(null);
  const [theme, setTheme] = useState(() => {
    // Default is dark mode as per requirements
    const saved = localStorage.getItem('theme');
    return saved || 'dark';
  });

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const fetchHistory = async () => {
    try {
      const res = await fetch('/api/history');
      if (res.ok) {
        const data = await res.json();
        setHistoryList(data);
      }
    } catch (e) {
      console.error("Failed to fetch history", e);
    }
  };

  const fetchInterrupted = async () => {
    try {
      const res = await fetch('/api/dd_report/interrupted');
      if (res.ok) {
        const data = await res.json();
        setInterruptedRuns(data);
      }
    } catch (e) {
      console.error("Failed to fetch interrupted runs", e);
    }
  };

  useEffect(() => {
    fetchHistory();
    fetchInterrupted();
  }, []);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  const startPipeline = (data) => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    setGlobalError(null);
    setCompanyDetails(data);
    setResumeRunId(null);
    setView('processing');
  };

  const handleResumePipeline = (run) => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    setGlobalError(null);
    setCompanyDetails({ company_name: run.vendor_name });
    setResumeRunId(run.run_id);
    setView('processing');
  };

  const handleProcessingComplete = (actualReport, jobId) => {
    setReport(actualReport);
    setCurrentJobId(jobId);
    setView('dashboard');
    setIsGraphOpen((actualReport.supply_chain && actualReport.supply_chain.length > 0) || !!actualReport.parent_company);
    fetchHistory(); // Refresh history
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      new Notification('Research Complete', {
        body: `Due diligence report for ${actualReport.vendor_name} is ready!`,
      });
    }
  };

  const handleProcessingError = (errMsg) => {
    setGlobalError(errMsg);
    setView('input');
  };

  const handleProcessingCancel = () => {
    setCompanyDetails(null);
    setResumeRunId(null);
    setView('input');
    fetchInterrupted();
  };

  const handleInstantMock = (data) => {
    setGlobalError(null);
    setCompanyDetails(data);
    const mockData = generateMockReport(data);
    handleProcessingComplete(mockData);
  };

  const handleReset = () => {
    setCompanyDetails(null);
    setReport(null);
    setGlobalError(null);
    setIsGraphOpen(false);
    setSelectedSupplier(null);
    setCurrentJobId(null);
    setResumeRunId(null);
    setView('input');
  };

  const handleLoadHistory = async (jobId) => {
    try {
      const res = await fetch(`/api/history/${jobId}`);
      if (res.ok) {
        const historicalReport = await res.json();
        setCompanyDetails(null);
        setReport(historicalReport);
        setSelectedSupplier(null);
        setCurrentJobId(jobId);
        setIsGraphOpen((historicalReport.supply_chain && historicalReport.supply_chain.length > 0) || !!historicalReport.parent_company);
        setView('dashboard');
      }
    } catch (e) {
      console.error("Failed to load historical report", e);
    }
  };

  return (
    <div className="min-h-screen h-screen flex flex-col bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans selection:bg-blue-200 selection:dark:bg-blue-800 selection:dark:text-white transition-colors duration-300">
      {/* Navbar */}
      <nav className="shrink-0 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 z-10 transition-colors duration-300">
        <div className="max-w-[98%] 2xl:max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button 
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="p-2 -ml-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors mr-2"
              title="Toggle History Sidebar"
            >
              <History className="w-5 h-5" />
            </button>
            <Shield className="w-8 h-8 text-blue-600 dark:text-blue-500" />
            <span className="font-bold text-xl tracking-tight text-slate-800 dark:text-slate-100">Vendor Due Diligence</span>
          </div>
          <div className="flex items-center gap-4">
            {view === 'dashboard' && (
              <button onClick={handleReset} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold transition shadow-sm">
                New Report
              </button>
            )}
            <button 
              onClick={toggleTheme}
              className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors border border-slate-200 dark:border-slate-700"
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Sun className="w-5 h-5 text-amber-400" /> : <Moon className="w-5 h-5 text-indigo-600" />}
            </button>
          </div>
        </div>
      </nav>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className={`${isSidebarOpen ? 'w-72' : 'w-0'} shrink-0 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 transition-all duration-300 overflow-y-auto flex flex-col`}>
          <div className="flex border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 sticky top-0 z-10">
            <button
              onClick={() => setActiveSidebarTab('history')}
              className={`flex-1 py-3 text-sm font-semibold transition-colors flex items-center justify-center gap-2 ${
                activeSidebarTab === 'history' 
                  ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400 bg-white dark:bg-slate-800' 
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 bg-slate-50 dark:bg-slate-900'
              }`}
            >
              <Clock className="w-4 h-4" /> History
            </button>
            <button
              onClick={() => setActiveSidebarTab('interrupted')}
              className={`flex-1 py-3 text-sm font-semibold transition-colors flex items-center justify-center gap-2 ${
                activeSidebarTab === 'interrupted' 
                  ? 'text-amber-600 dark:text-amber-400 border-b-2 border-amber-600 dark:border-amber-400 bg-white dark:bg-slate-800' 
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 bg-slate-50 dark:bg-slate-900'
              }`}
            >
              <PlaySquare className="w-4 h-4" /> Interrupted
              {interruptedRuns.length > 0 && (
                <span className="bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 text-[10px] py-0.5 px-2 rounded-full font-bold">
                  {interruptedRuns.length}
                </span>
              )}
            </button>
          </div>

          {activeSidebarTab === 'interrupted' ? (
            <>
              {interruptedRuns.length > 0 && (
                <div className="p-2 flex justify-end border-b border-slate-200 dark:border-slate-800">
                  <button 
                    onClick={() => {
                      setIsEditingInterrupted(!isEditingInterrupted);
                      setSelectedInterruptedItems(new Set());
                    }}
                    className={`p-1.5 rounded-md text-sm transition-colors flex items-center gap-1 ${isEditingInterrupted ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400' : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'}`}
                  >
                    <Edit2 className="w-3.5 h-3.5" /> Edit
                  </button>
                </div>
              )}

              {isEditingInterrupted && selectedInterruptedItems.size > 0 && (
                <div className="p-2 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
                  <button
                    onClick={async () => {
                      if (window.confirm(`Are you sure you want to delete ${selectedInterruptedItems.size} interrupted run(s)?`)) {
                        try {
                          await fetch('/api/dd_report/interrupted', {
                            method: 'DELETE',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ job_ids: Array.from(selectedInterruptedItems) })
                          });
                          setIsEditingInterrupted(false);
                          setSelectedInterruptedItems(new Set());
                          fetchInterrupted();
                        } catch (e) {
                          console.error("Failed to delete interrupted runs", e);
                        }
                      }
                    }}
                    className="w-full flex items-center justify-center gap-2 py-2 bg-red-100 hover:bg-red-200 dark:bg-red-900/30 dark:hover:bg-red-900/50 text-red-600 dark:text-red-400 font-semibold text-sm rounded-lg transition-colors border border-red-200 dark:border-red-800/50"
                  >
                    <Trash2 className="w-4 h-4" /> Delete ({selectedInterruptedItems.size})
                  </button>
                </div>
              )}

              <div className="p-2 space-y-1">
                {interruptedRuns.length === 0 ? (
                  <p className="text-sm text-slate-500 dark:text-slate-400 p-2 text-center italic">No interrupted runs</p>
                ) : (
                  interruptedRuns.map((run) => (
                    <div
                      key={run.run_id}
                      onClick={() => {
                        if (isEditingInterrupted) {
                          const newSet = new Set(selectedInterruptedItems);
                          if (newSet.has(run.run_id)) {
                            newSet.delete(run.run_id);
                          } else {
                            newSet.add(run.run_id);
                          }
                          setSelectedInterruptedItems(newSet);
                        } else {
                          handleResumePipeline(run);
                        }
                      }}
                      className={`w-full text-left p-3 rounded-lg transition-colors border group flex items-start gap-3 cursor-pointer ${
                        isEditingInterrupted && selectedInterruptedItems.has(run.run_id)
                          ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
                          : 'border-transparent hover:bg-slate-100 dark:hover:bg-slate-800 hover:border-slate-200 dark:hover:border-slate-700'
                      }`}
                    >
                      {isEditingInterrupted && (
                        <div className="pt-0.5 shrink-0">
                          <input 
                            type="checkbox" 
                            checked={selectedInterruptedItems.has(run.run_id)}
                            readOnly
                            className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500 cursor-pointer"
                          />
                        </div>
                      )}
                      <div className="flex-1 min-w-0 flex flex-col gap-1">
                        <div className="flex justify-between items-center w-full">
                          <span className="font-semibold text-sm truncate text-slate-800 dark:text-slate-200 group-hover:text-blue-600 dark:group-hover:text-blue-400">{run.vendor_name}</span>
                          {!isEditingInterrupted && (
                            <ArrowRight className="w-4 h-4 text-amber-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                          )}
                        </div>
                        <span className="text-xs text-slate-500 dark:text-slate-400">{new Date(run.started_at).toLocaleString()}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </>
          ) : (
            <>
              {historyList.length > 0 && (
                <div className="p-2 flex justify-end border-b border-slate-200 dark:border-slate-800">
                  <button 
                    onClick={() => {
                      setIsEditingHistory(!isEditingHistory);
                      setSelectedHistoryItems(new Set());
                    }}
                    className={`p-1.5 rounded-md text-sm transition-colors flex items-center gap-1 ${isEditingHistory ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400' : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'}`}
                  >
                    <Edit2 className="w-3.5 h-3.5" /> Edit
                  </button>
                </div>
              )}
              
              {isEditingHistory && selectedHistoryItems.size > 0 && (
                <div className="p-2 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
                  <button
                    onClick={async () => {
                      if (window.confirm(`Are you sure you want to delete ${selectedHistoryItems.size} report(s)?`)) {
                        try {
                          await fetch('/api/history', {
                            method: 'DELETE',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ job_ids: Array.from(selectedHistoryItems) })
                          });
                          setIsEditingHistory(false);
                          setSelectedHistoryItems(new Set());
                          fetchHistory();
                        } catch (e) {
                          console.error("Failed to delete history", e);
                        }
                      }
                    }}
                    className="w-full flex items-center justify-center gap-2 py-2 bg-red-100 hover:bg-red-200 dark:bg-red-900/30 dark:hover:bg-red-900/50 text-red-600 dark:text-red-400 font-semibold text-sm rounded-lg transition-colors border border-red-200 dark:border-red-800/50"
                  >
                    <Trash2 className="w-4 h-4" /> Delete ({selectedHistoryItems.size})
                  </button>
                </div>
              )}

              <div className="p-2 space-y-1">
                {historyList.length === 0 ? (
                  <p className="text-sm text-slate-500 dark:text-slate-400 p-2 text-center italic">No history found</p>
                ) : (
                  historyList.map((item) => (
                    <div
                      key={item.job_id}
                      onClick={() => {
                        if (isEditingHistory) {
                          const newSet = new Set(selectedHistoryItems);
                          if (newSet.has(item.job_id)) {
                            newSet.delete(item.job_id);
                          } else {
                            newSet.add(item.job_id);
                          }
                          setSelectedHistoryItems(newSet);
                        } else {
                          handleLoadHistory(item.job_id);
                        }
                      }}
                      className={`w-full text-left p-3 rounded-lg transition-colors border group flex items-start gap-3 cursor-pointer ${
                        isEditingHistory && selectedHistoryItems.has(item.job_id) 
                          ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800' 
                          : 'border-transparent hover:bg-slate-100 dark:hover:bg-slate-800 hover:border-slate-200 dark:hover:border-slate-700'
                      }`}
                    >
                      {isEditingHistory && (
                        <div className="pt-0.5 shrink-0">
                          <input 
                            type="checkbox" 
                            checked={selectedHistoryItems.has(item.job_id)}
                            readOnly
                            className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500 cursor-pointer"
                          />
                        </div>
                      )}
                      <div className="flex-1 min-w-0 flex flex-col gap-1">
                        <div className="flex justify-between items-center w-full">
                          <span className="font-semibold text-sm truncate text-slate-800 dark:text-slate-200 group-hover:text-blue-600 dark:group-hover:text-blue-400">{item.company_name}</span>
                          <div className="flex items-center" title={item.overall_risk}>
                            {item.overall_risk === Severity.CRITICAL && <div className="w-2.5 h-2.5 rounded-full bg-red-900 animate-pulse"></div>}
                            {item.overall_risk === Severity.HIGH && <div className="w-2.5 h-2.5 rounded-full bg-red-500"></div>}
                            {item.overall_risk === Severity.MEDIUM && <div className="w-2.5 h-2.5 rounded-full bg-amber-500"></div>}
                            {item.overall_risk === Severity.LOW && <div className="w-2.5 h-2.5 rounded-full bg-green-500"></div>}
                            {item.overall_risk === Severity.INFO && <div className="w-2.5 h-2.5 rounded-full bg-blue-500"></div>}
                          </div>
                        </div>
                        <span className="text-xs text-slate-500 dark:text-slate-400">{new Date(item.timestamp).toLocaleString()}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[98%] 2xl:max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-12">
            {view === 'input' && (
              <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div className="text-center mb-10 max-w-2xl mx-auto">
                  <h1 className="text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-4 tracking-tight">Automated Vendor Risk Assessment</h1>
                  <p className="text-lg text-slate-600 dark:text-slate-400">
                    Trigger a multi-agent orchestrated workflow.
                  </p>
                </div>
                
                {globalError && (
                  <div className="max-w-2xl mx-auto mb-6 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 rounded-lg flex items-start gap-3 text-red-700 dark:text-red-400 animate-in fade-in zoom-in-95 duration-300">
                    <ShieldX className="w-5 h-5 shrink-0 mt-0.5" />
                    <div>
                      <h3 className="font-bold">Pipeline Error</h3>
                      <p className="text-sm mt-1">{globalError}</p>
                    </div>
                  </div>
                )}
                
                <InputForm onSubmit={startPipeline} onInstantMock={handleInstantMock} />
              </div>
            )}

            {view === 'processing' && companyDetails && (
              <div className="animate-in fade-in zoom-in-95 duration-300 flex flex-col items-center">
                <div className="mb-8 text-center">
                  <h2 className="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-2">Orchestrating Agents...</h2>
                  <p className="text-slate-500 dark:text-slate-400">The FlowEngine is passing context to the A2A network.</p>
                </div>
                <ProcessingTerminal 
                  companyDetails={companyDetails} 
                  onComplete={handleProcessingComplete} 
                  onError={handleProcessingError}
                  onCancel={handleProcessingCancel}
                  resumeRunId={resumeRunId}
                />
              </div>
            )}

            {view === 'dashboard' && report && (
              <div className={`animate-in fade-in slide-in-from-bottom-8 duration-700 flex ${isGraphOpen ? 'gap-6 flex-row items-start' : 'flex-col'}`}>
                
                {/* Left Pane: Graph (only visible on desktop if open) */}
                {isGraphOpen && (
                  <div className="hidden lg:block w-1/2 shrink-0 h-[calc(100vh-8rem)] sticky top-6 rounded-xl overflow-hidden shadow-sm border border-slate-200 dark:border-slate-700">
                    <SupplyChainGraph 
                      report={report} 
                      theme={theme}
                      onNodeSelect={(supplierReport) => setSelectedSupplier(supplierReport)}
                    />
                  </div>
                )}
                
                {/* Right Pane (or full width): Dashboard */}
                <div className={`flex-1 w-full ${isGraphOpen ? 'lg:w-1/2' : ''}`}>
                  <Dashboard 
                    report={selectedSupplier || report} 
                    rootReport={report}
                    onReset={handleReset} 
                    onResetSupplier={() => setSelectedSupplier(null)}
                    theme={theme}
                    isGraphOpen={isGraphOpen}
                    onToggleGraph={() => setIsGraphOpen(!isGraphOpen)}
                    jobId={currentJobId}
                  />
                </div>
              </div>
            )}

          </div>
        </main>
      </div>
    </div>
  );
}