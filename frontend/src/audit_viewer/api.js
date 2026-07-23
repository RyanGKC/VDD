export const fetchAuditGraph = async (runId, companyName) => {
  const params = new URLSearchParams({ run_id: runId, company_name: companyName });
  const response = await fetch(`/api/audit/graph?${params}`);
  if (!response.ok) throw new Error('Failed to fetch audit trail');
  return response.json();
};

export const fetchRawChunks = async (eventId) => {
  const response = await fetch(`/api/audit/chunks?${new URLSearchParams({ event_id: eventId })}`);
  if (!response.ok) throw new Error('Failed to fetch retained evidence');
  return response.json();
};
