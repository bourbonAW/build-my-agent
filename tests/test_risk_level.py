"""Test risk level functionality."""

import pytest

from bourbon.tools import RiskLevel, get_tool_with_metadata


class TestRiskLevels:
    """Test tool risk level assignment."""
    
    def test_bash_is_high_risk(self):
        """bash tool should be HIGH risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        assert tool.risk_level == RiskLevel.HIGH
    
    def test_read_file_is_low_risk(self):
        """read_file tool should be LOW risk."""
        tool = get_tool_with_metadata("read_file")
        assert tool is not None
        assert tool.risk_level == RiskLevel.LOW
    
    def test_write_file_is_medium_risk(self):
        """write_file tool should be MEDIUM risk."""
        tool = get_tool_with_metadata("write_file")
        assert tool is not None
        assert tool.risk_level == RiskLevel.MEDIUM
    
    def test_edit_file_is_medium_risk(self):
        """edit_file tool should be MEDIUM risk."""
        tool = get_tool_with_metadata("edit_file")
        assert tool is not None
        assert tool.risk_level == RiskLevel.MEDIUM
    
    def test_rg_search_is_low_risk(self):
        """rg_search tool should be LOW risk."""
        tool = get_tool_with_metadata("rg_search")
        assert tool is not None
        assert tool.risk_level == RiskLevel.LOW
    
    def test_ast_grep_search_is_low_risk(self):
        """ast_grep_search tool should be LOW risk."""
        tool = get_tool_with_metadata("ast_grep_search")
        assert tool is not None
        assert tool.risk_level == RiskLevel.LOW
    
    def test_skill_is_low_risk(self):
        """skill tool should be LOW risk."""
        tool = get_tool_with_metadata("skill")
        assert tool is not None
        assert tool.risk_level == RiskLevel.LOW


class TestHighRiskDetection:
    """Test high-risk operation detection for bash."""
    
    def test_pip_install_is_high_risk(self):
        """pip install commands should be detected as high-risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        
        assert tool.is_high_risk_operation({"command": "pip install numpy"})
        assert tool.is_high_risk_operation({"command": "pip3 install numpy"})
        assert tool.is_high_risk_operation({"command": "pip install numpy==1.0.0"})
    
    def test_pip_uninstall_is_high_risk(self):
        """pip uninstall commands should be detected as high-risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        
        assert tool.is_high_risk_operation({"command": "pip uninstall numpy"})
    
    def test_apt_commands_are_high_risk(self):
        """apt commands should be detected as high-risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        
        assert tool.is_high_risk_operation({"command": "apt install nginx"})
        assert tool.is_high_risk_operation({"command": "apt-get update"})
    
    def test_rm_commands_are_high_risk(self):
        """rm commands should be detected as high-risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        
        assert tool.is_high_risk_operation({"command": "rm file.txt"})
        assert tool.is_high_risk_operation({"command": "rm -rf directory/"})
    
    def test_sudo_is_high_risk(self):
        """sudo commands should be detected as high-risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        
        assert tool.is_high_risk_operation({"command": "sudo apt update"})
    
    def test_safe_commands_are_not_high_risk(self):
        """Safe commands like ls, cat should not be high-risk."""
        tool = get_tool_with_metadata("bash")
        assert tool is not None
        
        assert not tool.is_high_risk_operation({"command": "ls -la"})
        assert not tool.is_high_risk_operation({"command": "cat file.txt"})
        assert not tool.is_high_risk_operation({"command": "echo hello"})
    
    def test_read_file_is_always_low_risk(self):
        """read_file should never be high-risk regardless of path."""
        tool = get_tool_with_metadata("read_file")
        assert tool is not None
        
        assert not tool.is_high_risk_operation({"path": "/etc/passwd"})
        assert not tool.is_high_risk_operation({"path": "important.py"})
