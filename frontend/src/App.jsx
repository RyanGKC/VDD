import React, { useState, useEffect, useRef } from 'react';
import { 
  ShieldAlert, ShieldCheck, Shield, AlertTriangle, 
  CheckCircle, Info, Building2, Globe, FileText, 
  MapPin, Landmark, ArrowRight, Loader2, PlaySquare,
  Activity, FileSearch, ShieldX, Sun, Moon, ChevronLeft, ChevronRight, Home
} from 'lucide-react';
import { 
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, 
  CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar
} from 'recharts';
import ReactFlow, { Controls, Background, MarkerType } from 'reactflow';
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
    vendor_name: companyDetails.company_name,
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
    generated_at: new Date().toISOString()
  };
};

// --- Components ---
export const getSeverityIcon = (sev) => {
  switch(sev) {
    case Severity.CRITICAL: return <ShieldX className="w-8 h-8 text-red-900" />;
    case Severity.HIGH: return <ShieldAlert className="w-8 h-8 text-red-500" />;
    case Severity.MEDIUM: return <AlertTriangle className="w-8 h-8 text-amber-500" />;
    case Severity.LOW: return <Info className="w-8 h-8 text-green-500" />;
    default: return <ShieldCheck className="w-8 h-8 text-blue-500" />;
  }
};


const InputForm = ({ onSubmit }) => {
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
    max_suppliers_per_node: 3
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

const ProcessingTerminal = ({ onComplete, onError, onCancel, companyDetails }) => {
  const [logs, setLogs] = useState([]);
  const endOfLogsRef = useRef(null);
  const abortControllerRef = useRef(null);
  
  useEffect(() => {
    endOfLogsRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    let isMounted = true;
    abortControllerRef.current = new AbortController();
    
    const runBackend = async () => {
      setLogs([{ text: `SYSTEM: Initializing DDContext for ${companyDetails.company_name}`, time: new Date().toLocaleTimeString() }]);
      setLogs(prev => [...prev, { text: "SYSTEM: Connecting to backend... (this may take a few minutes as agents process data)", time: new Date().toLocaleTimeString() }]);
      
      const jobId = Math.random().toString(36).substring(2, 15);
      
      const statusInterval = setInterval(async () => {
        if (!isMounted) return;
        try {
          const statusRes = await fetch(`/api/dd_status/${jobId}`);
          if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.logs && statusData.logs.length > 0) {
              setLogs(statusData.logs);
            }
          }
        } catch (e) {
          // Ignore fetch errors during polling
        }
      }, 2000);
      
      try {
        const response = await fetch('/api/dd_report', {
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
            job_id: jobId
          }),
          signal: abortControllerRef.current.signal
        });
        
        clearInterval(statusInterval);
        
        if (!response.ok) {
           const errText = await response.text();
           throw new Error(`API Error: ${response.status} ${errText}`);
        }
        
        const reportData = await response.json();
        
        if (isMounted) {
          clearInterval(statusInterval);
          setLogs(prev => [...prev, { text: "SYSTEM: Pipeline Complete. Generating Report.", time: new Date().toLocaleTimeString() }]);
          setTimeout(() => {
            if (isMounted) onComplete(reportData);
          }, 1000);
        }
      } catch (err) {
        clearInterval(statusInterval);
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
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [companyDetails, onComplete, onError]);

  const handleCancelClick = () => {
    if (window.confirm("Are you sure you want to interrupt the research flow? All current progress will be lost.")) {
      if (abortControllerRef.current) abortControllerRef.current.abort();
      onCancel();
    }
  };

  return (
    <div className="max-w-3xl mx-auto w-full">
      <div className="bg-slate-900 rounded-xl overflow-hidden shadow-2xl border border-slate-700 dark:border-slate-800">
        <div className="bg-slate-950 px-4 py-3 flex items-center justify-between border-b border-slate-800">
          <div className="flex gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500"></div>
            <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
            <div className="w-3 h-3 rounded-full bg-green-500"></div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-slate-400 text-xs font-mono flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> FlowEngine Executing
            </span>
            <button 
              onClick={handleCancelClick}
              className="text-xs text-red-400 hover:text-red-300 font-semibold transition"
            >
              Cancel
            </button>
          </div>
        </div>
        <div className="p-6 font-mono text-sm h-96 overflow-y-auto space-y-2">
          {logs.map((log, i) => (
            <div key={i} className={`flex gap-3 ${log.isError ? 'text-red-400' : log.isSuper ? 'text-purple-400' : 'text-emerald-400'}`}>
              <span className="text-slate-500 shrink-0">[{log.time}]</span>
              <span className={log.isError ? 'font-bold' : ''}>{log.text}</span>
            </div>
          ))}
          <div ref={endOfLogsRef} />
        </div>
      </div>
    </div>
  );
};

const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const getLayoutedElements = (nodes, edges, direction = 'TB') => {
  const nodeWidth = 220;
  const nodeHeight = 90;
  dagreGraph.setGraph({ rankdir: direction });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    node.position = {
      x: nodeWithPosition.x - nodeWidth / 2,
      y: nodeWithPosition.y - nodeHeight / 2,
    };
    return node;
  });

  return { nodes: layoutedNodes, edges };
};

const CustomNode = ({ data }) => {
  return (
    <div className="bg-white dark:bg-slate-800 border-2 rounded-lg p-3 shadow-md w-[220px] flex flex-col items-center transition-all hover:shadow-lg hover:-translate-y-1" style={{borderColor: data.color}}>
      <div className="flex flex-col items-center gap-1 mb-2 w-full">
        {data.icon}
        <span className="font-bold text-slate-800 dark:text-slate-100 text-sm text-center line-clamp-2 w-full">{data.label}</span>
      </div>
      <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border`} style={{color: data.color, borderColor: data.color}}>
        {data.risk} Risk
      </span>
    </div>
  );
};
const nodeTypes = { custom: CustomNode };

const SupplyChainGraph = ({ report, theme, onNodeSelect }) => {
  const initialNodes = [];
  const initialEdges = [];
  
  const buildGraph = (node, parentId = null) => {
    const nodeId = node.vendor_name;
    
    if (!initialNodes.find(n => n.id === nodeId)) {
      initialNodes.push({
        id: nodeId,
        type: 'custom',
        data: { 
          label: node.vendor_name,
          risk: node.overall_risk,
          color: SEVERITY_COLORS[node.overall_risk],
          icon: getSeverityIcon(node.overall_risk),
          fullReport: node
        }
      });
    }

    if (parentId) {
      initialEdges.push({
        id: `${parentId}->${nodeId}`,
        source: parentId,
        target: nodeId,
        type: 'smoothstep',
        className: 'animated-reverse',
        style: { stroke: theme === 'dark' ? '#94a3b8' : '#64748b', strokeWidth: 2 }
      });
    }

    if (node.supply_chain && node.supply_chain.length > 0) {
      node.supply_chain.forEach(child => buildGraph(child, nodeId));
    }
  };

  buildGraph(report);
  
  const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(initialNodes, initialEdges, 'TB');
  
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
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        className={theme === 'dark' ? 'dark' : ''}
      >
        <Background color={theme === 'dark' ? '#334155' : '#cbd5e1'} gap={16} />
        <Controls />
      </ReactFlow>
    </div>
  );
};

const Dashboard = ({ report, rootReport, onReset, onResetSupplier, theme }) => {
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
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* Header Area */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white dark:bg-slate-900 p-6 rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 transition-all duration-300">
        <div>
          {rootReport && rootReport.vendor_name !== report.vendor_name && (
            <div className="flex items-center gap-2 mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">
              <button onClick={onResetSupplier} className="hover:text-blue-500 transition-colors flex items-center gap-1">
                <Home className="w-4 h-4" />
                {rootReport.vendor_name}
              </button>
              <ChevronRight className="w-4 h-4" />
              <span className="text-slate-800 dark:text-slate-200">{report.vendor_name}</span>
            </div>
          )}
          <h1 className="text-3xl font-bold text-slate-800 dark:text-slate-100 flex items-center gap-3">
            {report.vendor_name}
          </h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">Generated: {new Date(report.generated_at).toLocaleString()}</p>
        </div>
        <div className="flex items-center gap-6">
          <div className="flex flex-col items-end">
            <span className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Overall Risk</span>
            <div className="flex items-center gap-2 mt-1">
              {getSeverityIcon(report.overall_risk)}
              <span className={`text-2xl font-bold uppercase`} style={{color: SEVERITY_COLORS[report.overall_risk]}}>
                {report.overall_risk}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3 ml-4">
            {report.audit_log && (
              <button onClick={handleDownloadAuditLog} className="flex items-center gap-2 px-4 py-2 bg-blue-100 hover:bg-blue-200 dark:bg-blue-900/50 dark:hover:bg-blue-800/50 text-blue-700 dark:text-blue-300 rounded-lg text-sm font-semibold transition border border-blue-200 dark:border-blue-800">
                <FileText className="w-4 h-4" />
                Audit Log
              </button>
            )}
            <button onClick={onReset} className="px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg text-sm font-semibold transition">
              New Report
            </button>
          </div>
        </div>
      </div>

      {/* Exec Summary */}
      <div className="bg-slate-800 dark:bg-slate-900/50 dark:border dark:border-slate-800 text-white p-6 rounded-xl shadow-sm transition-all duration-300">
        <h2 className="text-lg font-semibold text-slate-300 dark:text-slate-400 uppercase tracking-wider mb-3">Executive Summary</h2>
        <p className="text-lg leading-relaxed text-slate-100">{report.executive_summary}</p>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-slate-900 p-6 rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 transition-all duration-300">
          <h3 className="text-base font-bold text-slate-800 dark:text-slate-200 mb-4 text-center">Red Flags by Severity</h3>
          <div className="h-64">
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
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
                <Radar name="Risk Score" dataKey="A" stroke="#3b82f6" fill="#3b82f6" fillOpacity={theme === 'dark' ? 0.35 : 0.5} />
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
            Object.entries(redFlagsByCategory).map(([category, flags]) => (
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
                Object.entries(strengthsByCategory).map(([category, flags]) => (
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

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  const startPipeline = (data) => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    setGlobalError(null);
    setCompanyDetails(data);
    setView('processing');
  };

  const handleProcessingComplete = (actualReport) => {
    setReport(actualReport);
    setView('dashboard');
    setIsGraphOpen(actualReport.supply_chain && actualReport.supply_chain.length > 0);
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
    setView('input');
  };

  const handleReset = () => {
    setCompanyDetails(null);
    setReport(null);
    setGlobalError(null);
    setIsGraphOpen(false);
    setSelectedSupplier(null);
    setView('input');
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans selection:bg-blue-200 selection:dark:bg-blue-800 selection:dark:text-white transition-colors duration-300">
      {/* Navbar */}
      <nav className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-10 transition-colors duration-300">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-8 h-8 text-blue-600 dark:text-blue-500" />
            <span className="font-bold text-xl tracking-tight text-slate-800 dark:text-slate-100">A2A Due Diligence</span>
          </div>
          <div className="flex items-center gap-4">
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

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-12">
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
            
            <InputForm onSubmit={startPipeline} />
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
            />
          </div>
        )}

        {view === 'dashboard' && report && (
          <div className={`animate-in fade-in slide-in-from-bottom-8 duration-700 flex ${isGraphOpen ? 'gap-6 flex-row items-start' : 'flex-col'}`}>
            
            {/* Toggle Button for Desktop */}
            {report.supply_chain && report.supply_chain.length > 0 && (
              <div className="fixed left-4 top-1/2 -translate-y-1/2 z-20 hidden lg:block">
                <button 
                  onClick={() => setIsGraphOpen(!isGraphOpen)}
                  className="bg-white dark:bg-slate-800 p-3 rounded-full shadow-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition focus:outline-none focus:ring-2 focus:ring-blue-500"
                  title={isGraphOpen ? "Hide Supply Chain Graph" : "Show Supply Chain Graph"}
                >
                  {isGraphOpen ? <ChevronLeft className="w-6 h-6" /> : <ChevronRight className="w-6 h-6" />}
                </button>
              </div>
            )}

            {/* Left Pane: Graph (only visible on desktop if open) */}
            {isGraphOpen && (
              <div className="hidden lg:block w-1/2 shrink-0 h-[calc(100vh-8rem)] sticky top-24 rounded-xl overflow-hidden shadow-sm border border-slate-200 dark:border-slate-700">
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
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}