export const fetchAuditGraph = async (runId, companyName) => {
  const url = new URL('http://localhost:8000/api/audit/graph');
  url.searchParams.append('run_id', runId);
  url.searchParams.append('company_name', companyName);
  
  const response = await fetch(url);
  if (!response.ok) throw new Error('Failed to fetch audit graph');
  return response.json();
};

export const fetchRawChunks = async (chunkIds) => {
  const url = new URL('http://localhost:8000/api/audit/chunks');
  chunkIds.forEach(id => url.searchParams.append('chunk_ids', id));
  
  const response = await fetch(url);
  if (!response.ok) throw new Error('Failed to fetch raw chunks');
  return response.json();
};
