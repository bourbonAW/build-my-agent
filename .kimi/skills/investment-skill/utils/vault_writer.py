"""
Vault Writer - Utility to write investment reports to Obsidian vault
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


class VaultWriter:
    """Write investment analysis outputs to Obsidian vault"""
    
    def __init__(self, vault_path: Optional[str] = None):
        """Initialize vault writer
        
        Args:
            vault_path: Path to Obsidian vault. Defaults to ~/vault-notes
        """
        self.vault_path = Path(vault_path or os.path.expanduser("~/vault-notes"))
        self.daily_path = self.vault_path / "daily"
        self.knowledge_path = self.vault_path / "knowledge" / "investment"
        
        # Ensure directories exist
        self.daily_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_path.mkdir(parents=True, exist_ok=True)
    
    def write_daily_report(self, content: str, date: Optional[datetime] = None, 
                          suffix: str = "investment") -> str:
        """Write daily investment report
        
        Args:
            content: Markdown content to write
            date: Report date (defaults to today)
            suffix: File suffix (e.g., 'investment', 'fund_report')
            
        Returns:
            Path to written file
        """
        date = date or datetime.now()
        filename = f"{date.strftime('%Y-%m-%d')}_{suffix}.md"
        filepath = self.daily_path / filename
        
        # Add metadata header if not present
        if not content.startswith("---"):
            content = self._add_metadata(content, date, suffix)
        
        filepath.write_text(content, encoding='utf-8')
        return str(filepath)
    
    def write_knowledge_entry(self, content: str, category: str, 
                             filename: str) -> str:
        """Write knowledge base entry
        
        Args:
            content: Markdown content
            category: Knowledge category (portfolio, macro, industries)
            filename: Entry filename
            
        Returns:
            Path to written file
        """
        category_path = self.knowledge_path / category
        category_path.mkdir(parents=True, exist_ok=True)
        
        filepath = category_path / filename
        
        # Add metadata if not present
        if not content.startswith("---"):
            date = datetime.now()
            content = self._add_metadata(content, date, category)
        
        filepath.write_text(content, encoding='utf-8')
        return str(filepath)
    
    def append_to_daily(self, content: str, date: Optional[datetime] = None) -> str:
        """Append content to existing daily note
        
        Args:
            content: Content to append
            date: Target date (defaults to today)
            
        Returns:
            Path to updated file
        """
        date = date or datetime.now()
        filename = f"{date.strftime('%Y-%m-%d')}.md"
        filepath = self.daily_path / filename
        
        # Add investment section if file exists
        if filepath.exists():
            existing = filepath.read_text(encoding='utf-8')
            if "## Investment" not in existing:
                content = f"\n\n## Investment\n\n{content}"
            else:
                content = f"\n\n{content}"
            
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(content)
        else:
            # Create new daily note
            filepath.write_text(content, encoding='utf-8')
        
        return str(filepath)
    
    def create_link(self, target: str, display: Optional[str] = None) -> str:
        """Create Obsidian wiki-link
        
        Args:
            target: Link target path
            display: Display text (optional)
            
        Returns:
            Wiki-link string
        """
        if display:
            return f"[[{target}|{display}]]"
        return f"[[{target}]]"
    
    def link_to_fund(self, fund_code: str, fund_name: str) -> str:
        """Create link to fund analysis"""
        return self.create_link(f"knowledge/investment/portfolio/fund_{fund_code}", fund_name)
    
    def link_to_macro(self, report_name: str) -> str:
        """Create link to macro report"""
        return self.create_link(f"knowledge/investment/macro/{report_name}", "宏观分析")
    
    def _add_metadata(self, content: str, date: datetime, 
                     category: str) -> str:
        """Add YAML metadata to content"""
        metadata = f"""---
date: {date.strftime('%Y-%m-%d')}
category: {category}
generated_by: Investment Agent
---

"""
        return metadata + content
    
    def get_recent_reports(self, days: int = 7, suffix: str = "investment") -> list:
        """Get list of recent report files
        
        Args:
            days: Number of days to look back
            suffix: File suffix filter
            
        Returns:
            List of file paths
        """
        reports = []
        now = datetime.now()
        
        for i in range(days):
            date = now - __import__('datetime').timedelta(days=i)
            filename = f"{date.strftime('%Y-%m-%d')}_{suffix}.md"
            filepath = self.daily_path / filename
            
            if filepath.exists():
                reports.append(str(filepath))
        
        return reports
    
    def extract_fund_links(self, content: str) -> list:
        """Extract fund codes from content"""
        pattern = r'\b(\d{6})\b'
        return list(set(re.findall(pattern, content)))


# Convenience functions
def get_vault_writer() -> VaultWriter:
    """Get default vault writer instance"""
    return VaultWriter()


def write_investment_report(content: str, report_type: str = "daily") -> str:
    """Quick function to write investment report
    
    Args:
        content: Report content
        report_type: 'daily', 'fund', 'macro', or 'industry'
    
    Returns:
        Path to written file
    """
    writer = get_vault_writer()
    
    if report_type == "daily":
        return writer.write_daily_report(content, suffix="investment")
    elif report_type == "fund":
        return writer.write_daily_report(content, suffix="fund_report")
    elif report_type == "macro":
        return writer.write_knowledge_entry(
            content, 
            "macro", 
            f"liquidity_{datetime.now().strftime('%Y-%m')}.md"
        )
    elif report_type == "industry":
        return writer.write_knowledge_entry(
            content,
            "industries/semiconductor",
            f"analysis_{datetime.now().strftime('%Y-%m-%d')}.md"
        )
    else:
        return writer.write_daily_report(content, suffix=report_type)
