import React, { useState } from 'react';
import { Building2, Search, AlertCircle, Loader2 } from 'lucide-react';

export default function App() {
  const [companyName, setCompanyName] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  const handleCompare = async (e) => {
    e.preventDefault();
    if (!companyName.trim()) return;

    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const res = await fetch(`http://localhost:8003/api/compare_financials?company_name=${encodeURIComponent(companyName)}`);
      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }
      const data = await res.json();
      setResults(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const renderTable = (data, title) => {
    if (!data) return null;
    
    // Check if data is an array of objects
    if (!Array.isArray(data) || data.length === 0) {
      return (
        <div className="p-4 bg-yellow-900/20 text-yellow-200 rounded-lg border border-yellow-800/50">
          No structured data available.
        </div>
      );
    }

    const columns = Object.keys(data[0]);

    return (
      <div className="bg-slate-900 rounded-xl shadow-lg border border-slate-800 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-950/50">
          <h3 className="font-semibold text-slate-100">{title}</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left text-slate-300">
            <thead className="text-xs uppercase bg-slate-950/30 text-slate-400 border-b border-slate-800">
              <tr>
                {columns.map(col => (
                  <th key={col} className="px-6 py-3 whitespace-nowrap">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, idx) => (
                <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-800/50 transition-colors">
                  {columns.map(col => (
                    <td key={col} className="px-6 py-4 whitespace-nowrap">
                      {row[col] !== null && row[col] !== undefined ? String(row[col]) : '-'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8 flex justify-center bg-slate-950 text-slate-200 selection:bg-blue-500/30">
      <div className="max-w-7xl w-full">
        <div className="mb-8">
          <h1 className="text-3xl font-extrabold text-white mb-2 tracking-tight">Finance API Comparison</h1>
          <p className="text-slate-400">
            Compare the Income Statement data returned by the yfinance library and the Alpha Vantage API.
          </p>
        </div>

        <form onSubmit={handleCompare} className="mb-10 max-w-2xl bg-slate-900/80 p-6 rounded-2xl shadow-xl border border-slate-800 backdrop-blur-sm">
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-sm font-medium text-slate-300 mb-1.5 ml-1">Company Name / Ticker</label>
              <div className="relative group">
                <Building2 className="w-4 h-4 absolute left-3.5 top-3.5 text-slate-500 group-focus-within:text-blue-400 transition-colors" />
                <input 
                  type="text" 
                  required 
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="e.g. Apple Inc. or AAPL"
                  className="w-full pl-10 pr-4 py-3 bg-slate-950/50 border border-slate-700 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none rounded-xl transition-all placeholder:text-slate-600" 
                />
              </div>
            </div>
            <button 
              type="submit" 
              disabled={loading}
              className="flex items-center justify-center gap-2 px-8 py-3 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600 text-white rounded-xl font-semibold transition-all shadow-lg shadow-blue-900/20 h-[50px]"
            >
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Search className="w-5 h-5" />}
              Compare
            </button>
          </div>
          {error && (
            <div className="mt-4 p-4 bg-red-950/40 text-red-400 border border-red-900/50 rounded-xl flex gap-3 items-center text-sm shadow-inner">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <p>{error}</p>
            </div>
          )}
        </form>

        {results && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  yfinance Results
                </h2>
                <span className={`text-xs font-bold px-3 py-1.5 rounded-full ${results.yfinance.status === 'success' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                  {results.yfinance.status.toUpperCase()}
                </span>
              </div>
              {results.yfinance.status === 'error' ? (
                <div className="p-4 bg-red-950/40 text-red-400 rounded-xl flex gap-3 border border-red-900/50 shadow-inner">
                  <AlertCircle className="w-5 h-5 shrink-0" />
                  <p className="text-sm">{results.yfinance.error}</p>
                </div>
              ) : (
                renderTable(results.yfinance.data, "Income Statement")
              )}
            </div>

            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  Alpha Vantage Results
                </h2>
                <span className={`text-xs font-bold px-3 py-1.5 rounded-full ${results.fmp.status === 'success' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                  {results.fmp.status.toUpperCase()}
                </span>
              </div>
              {results.fmp.status === 'error' ? (
                <div className="p-4 bg-red-950/40 text-red-400 rounded-xl flex gap-3 border border-red-900/50 shadow-inner">
                  <AlertCircle className="w-5 h-5 shrink-0" />
                  <p className="text-sm">{results.fmp.error}</p>
                </div>
              ) : (
                renderTable(results.fmp.data, "Income Statement")
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
