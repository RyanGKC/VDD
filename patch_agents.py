import os
import re

AGENT_DEFAULTS = {
    "esg_agent.py": [
        '"{company} ESG report"',
        '"{company} environmental violations controversy"'
    ],
    "finances_agent.py": [
        '"{company} financial statements revenue"',
        '"{company} bankruptcy insolvency"'
    ],
    "kyb_agent.py": [
        '"{company} corporate registration details"',
        '"{company} headquarters address contact"'
    ],
    "licenses_agent.py": [
        '"{company} regulatory licenses certifications"',
        '"{company} regulatory fines loss of license"'
    ],
    "media_agent.py": [
        '"{company} scandal fraud controversy news"',
        '"{company} lawsuit litigation"'
    ],
    "profile_agent.py": [
        '"{company} business model products services"',
        '"{company} major competitors market share"'
    ],
    "resilience_agent.py": [
        '"{company} supply chain disruption cyber attack"',
        '"{company} operational resilience redundancy"'
    ],
    "sanctions_agent.py": [
        # Sanctions agent primarily uses OpenSanctions API, but if it falls back:
        '"{company} OFAC sanctions list"',
        '"{company} export control violations"'
    ],
    "shareholders_agent.py": [
        '"{company} ultimate beneficial owners UBO"',
        '"{company} major shareholders parent company"'
    ]
}

agents_dir = "/Users/ryangoh/VDD Prototype/agents"

for filename, defaults in AGENT_DEFAULTS.items():
    filepath = os.path.join(agents_dir, filename)
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Check if we already patched it
    if "def default_queries" in content:
        continue
        
    # Find `step = StepName.XXX`
    match = re.search(r'(    step = StepName\.[A-Z_]+)', content)
    if not match:
        print(f"Could not find step definition in {filename}")
        continue
        
    queries_str = ",\n            ".join(defaults)
    
    replacement = f"""{match.group(1)}

    @property
    def default_queries(self) -> list[str]:
        return [
            {queries_str}
        ]"""
        
    new_content = content.replace(match.group(1), replacement, 1)
    
    with open(filepath, 'w') as f:
        f.write(new_content)
    print(f"Patched {filename}")
