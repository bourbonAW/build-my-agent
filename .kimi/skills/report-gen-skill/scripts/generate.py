#!/usr/bin/env python3
"""Report generation script"""
import sys
import json
from datetime import datetime
from pathlib import Path

try:
    from jinja2 import Template
except ImportError:
    print(json.dumps({
        'success': False,
        'error': 'jinja2 not installed. Install with: uv pip install jinja2'
    }))
    sys.exit(1)


def main():
    args = json.loads(sys.stdin.read())
    title = args.get('title', 'Report')
    data = args.get('data', {})
    sections = args.get('sections', [])
    summary = args.get('summary', '')
    output_file = args.get('output_file')
    
    # Load template
    template_path = Path(__file__).parent.parent / 'templates' / 'report.md.j2'
    if template_path.exists():
        template = Template(template_path.read_text())
    else:
        # Default simple template
        template = Template("""# {{ title }}

Generated: {{ date }}

{% if summary %}
## Summary
{{ summary }}
{% endif %}

{% for section in sections %}
## {{ section.heading }}
{{ section.content }}
{% endfor %}
""")
    
    try:
        report = template.render(
            title=title,
            date=datetime.now().strftime('%Y-%m-%d %H:%M'),
            data=data,
            sections=sections,
            summary=summary,
        )
        
        result = {
            'success': True,
            'title': title,
            'report': report,
        }
        
        # Save to file if specified
        if output_file:
            output_path = Path(output_file)
            output_path.write_text(report)
            result['file_path'] = str(output_path.absolute())
        
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({
            'success': False,
            'error': str(e)
        }))


if __name__ == '__main__':
    main()
