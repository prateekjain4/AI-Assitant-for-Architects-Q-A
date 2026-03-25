from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from io import BytesIO
import datetime

# Brand colours
PRIMARY   = colors.HexColor('#1d4ed8')   # blue
SECONDARY = colors.HexColor('#f0f9ff')   # light blue bg
DARK      = colors.HexColor('#1e293b')
MUTED     = colors.HexColor('#64748b')
GREEN     = colors.HexColor('#16a34a')
RED       = colors.HexColor('#dc2626')
AMBER     = colors.HexColor('#d97706')
BORDER    = colors.HexColor('#e2e8f0')

def generate_planning_report(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Header ────────────────────────────────────────────────────
    header_data = [[
        Paragraph(
            '<font color="#1d4ed8" size="18"><b>ZoneSmart</b></font>'
            '<br/><font color="#64748b" size="9">Bangalore Building Regulations Report</font>',
            styles['Normal']
        ),
        Paragraph(
            f'<font color="#64748b" size="8">Generated on<br/>'
            f'<b>{datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")}</b></font>',
            ParagraphStyle('right', alignment=TA_RIGHT, parent=styles['Normal'])
        )
    ]]
    header_table = Table(header_data, colWidths=[120*mm, 50*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW',   (0,0), (-1,-1), 1, PRIMARY),
        ('BOTTOMPADDING',(0,0),(-1,-1), 8),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6*mm))

    # ── Location banner ───────────────────────────────────────────
    zone      = data.get('zone', 'N/A')
    locality  = data.get('locality', '')
    ward      = data.get('ward', '')
    confidence= data.get('confidence', '')

    location_text = f'{locality}, {ward}' if locality else 'Location not specified'
    conf_color    = '#16a34a' if confidence == 'precise' else '#d97706'
    conf_label    = '✓ Verified zone' if confidence == 'precise' else '⚠ Approximate zone'

    banner_data = [[
        Paragraph(
            f'<font size="11" color="white"><b>Zone: {zone}</b>  •  {location_text}</font>',
            styles['Normal']
        ),
        Paragraph(
            f'<font size="8" color="{conf_color}"><b>{conf_label}</b></font>',
            ParagraphStyle('right', alignment=TA_RIGHT, parent=styles['Normal'])
        )
    ]]
    banner_table = Table(banner_data, colWidths=[120*mm, 50*mm])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), PRIMARY),
        ('TEXTCOLOR',     (0,0), (-1,-1), colors.white),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), [4,4,4,4]),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (0,-1), 10),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 6*mm))

    # ── Key metrics row ───────────────────────────────────────────
    def metric_cell(label, value, unit=''):
        return Paragraph(
            f'<font size="8" color="#64748b">{label}</font><br/>'
            f'<font size="14" color="#1e293b"><b>{value}</b></font>'
            f'<font size="9" color="#64748b"> {unit}</font>',
            styles['Normal']
        )

    plot_area    = data.get('plot_area', 0)
    far          = data.get('far', 0)
    max_built    = data.get('max_built_area', 0)
    road_width   = data.get('road_width', 0)

    metrics_data = [[
        metric_cell('Plot Area',         f'{plot_area:,.0f}', 'sq ft'),
        metric_cell('FAR',               f'{far}',            ''),
        metric_cell('Max Built-up Area', f'{max_built:,.0f}', 'sq ft'),
        metric_cell('Road Width',        f'{road_width}',     'm'),
    ]]
    metrics_table = Table(metrics_data, colWidths=[42*mm]*4)
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), SECONDARY),
        ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
        ('LINEBEFORE',    (1,0), (-1,-1), 0.5, BORDER),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), [4,4,4,4]),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 6*mm))

    # ── Section heading helper ────────────────────────────────────
    def section_heading(title):
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            f'<font size="10" color="#1d4ed8"><b>{title}</b></font>',
            styles['Normal']
        ))
        story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=3*mm))

    # ── Setbacks table ────────────────────────────────────────────
    section_heading('Setback Requirements')
    setbacks = data.get('setbacks', {})
    setback_data = [
        ['Direction', 'Required Setback', 'Notes'],
        ['Front',     f"{setbacks.get('front', 'N/A')} m", 'From road boundary'],
        ['Rear',      f"{setbacks.get('rear',  'N/A')} m", 'From rear boundary'],
        ['Side',      f"{setbacks.get('side',  'N/A')} m", 'Each side boundary'],
    ]
    setback_table = Table(setback_data, colWidths=[45*mm, 45*mm, 80*mm])
    setback_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  PRIMARY),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, SECONDARY]),
        ('BOX',           (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
    ]))
    story.append(setback_table)

    # ── Fire rules ────────────────────────────────────────────────
    section_heading('Fire Safety Requirements')
    fire_rules = data.get('fire_rules', [])
    if fire_rules:
        for rule in fire_rules:
            story.append(Paragraph(
                f'<font size="9" color="#dc2626">●</font>'
                f'<font size="9"> {rule}</font>',
                ParagraphStyle('bullet', leftIndent=10, parent=styles['Normal'])
            ))
    else:
        story.append(Paragraph(
            '<font size="9" color="#16a34a">✓ No mandatory fire NOC required for this building height. '
            'Standard fire precautions apply as per NBC 2016.</font>',
            styles['Normal']
        ))

    story.append(Spacer(1, 3*mm))

    # ── AI Explanation ────────────────────────────────────────────
    section_heading('Regulatory Analysis')
    ai_text = data.get('ai_explanation', '')
    # Split into paragraphs and render each
    for para in ai_text.split('\n'):
        para = para.strip()
        if not para:
            story.append(Spacer(1, 2*mm))
            continue
        # Bold numbered headings like "1. **SETBACK ANALYSIS**"
        para = para.replace('**', '')
        story.append(Paragraph(
            f'<font size="9" color="#1e293b">{para}</font>',
            ParagraphStyle('body', leading=14, parent=styles['Normal'])
        ))

    # ── Footer ────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        '<font size="7" color="#94a3b8">'
        'This report is generated based on BDA RMP 2031 Zoning Regulations, BBMP Building Bylaws, '
        'and NBC 2016 Fire Safety norms. It is indicative in nature and should be verified with '
        'the relevant authority (BBMP / BDA) before plan submission. '
        'Generated by ZoneSmart — bangalore.zonesmart.in'
        '</font>',
        ParagraphStyle('footer', alignment=TA_CENTER, parent=styles['Normal'])
    ))

    doc.build(story)
    return buffer.getvalue()