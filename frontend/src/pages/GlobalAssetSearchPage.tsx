import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import Button from 'antd/es/button'
import Modal from 'antd/es/modal'
import Select from 'antd/es/select'
import { get, post } from '../api'
import { copyToClipboard } from '../utils'
import type { ZoneItem } from '../types/zone'
import type { TaskResultsResponse, TaskFacetResponse, PortOverviewRow, PortOverviewResponse, VulnResultDetail, FaviconItem } from '../types/result'
import 'font-awesome/css/font-awesome.min.css'
import '@fontsource/dm-sans/latin-400.css'
import '@fontsource/dm-sans/latin-500.css'
import '@fontsource/dm-sans/latin-600.css'
import '@fontsource/spectral/latin-500.css'
import '@fontsource/spectral/latin-600.css'
import '@fontsource/spectral/latin-500-italic.css'
import { useAuth } from '../contexts/AuthContext'

const FACET_LABELS: Record<string, string> = {
  protocol: '协议', port: '端口', title: '标题', product: '产品',
  country: '地区', province: '省份', city: '城市', isp: '运营商',
  ipc: 'IP段', status_code: '状态码', vuln: '漏洞', cve: 'CVE',
  cert: '证书主体', cert_org: '证书组织', cert_org_unit: '证书部门',
  uri_path: 'URI路径', icp: 'ICP备案', copyright: '版权信息',
}
const ALL_FACET_FIELDS = ['protocol', 'port', 'title', 'product', 'country', 'province', 'city', 'isp', 'ipc', 'status_code', 'vuln', 'cve', 'cert', 'cert_org', 'cert_org_unit', 'uri_path', 'icp', 'copyright']
const JUMP_PAGES = 10
const FAVICON_PAGE_SIZE = 20

const STYLES = `
:root {
  --bg: #f5f3f0; --surface: #f7f5f2; --surface-hover: #fafaf9;
  --text: #292524; --text-secondary: #78716c; --text-muted: #a8a29e;
  --accent: #0d9488; --accent-dim: #ccfbf1; --accent-bg: #fefefe;
  --warn: #d97706; --warn-bg: #fffbeb;
  --divider: #e7e5e4; --radius: 6px; --sidebar-w: 280px;
}
#asset-search-root * { box-sizing: border-box; margin: 0; padding: 0 }
#asset-search-root {
  font-family: 'DM Sans', -apple-system, sans-serif;
  background: var(--bg); color: var(--text);
  line-height: 1.6; min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
/* Top bar */
#asset-search-root .topbar {
  background: var(--surface); border-bottom: 1px solid var(--divider);
  padding: 0 32px; height: 56px; display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 50;
}
#asset-search-root .topbar h1 {
  font-family: 'Spectral', serif; font-size: 19px; font-weight: 600;
  letter-spacing: -.2px; color: var(--text);
}
#asset-search-root .topbar h1 em { font-style: italic; font-weight: 500; color: var(--accent) }
#asset-search-root .topbar .meta { display: flex; align-items: center; gap: 18px; font-size: 14px; color: var(--text-secondary) }
#asset-search-root .topbar .pill {
  background: var(--accent-bg); color: var(--accent); padding: 4px 14px;
  border-radius: 20px; font-weight: 500; font-size: 13px;
}
/* Shell */
#asset-search-root .shell { display: flex; min-height: calc(100vh - 56px) }
/* Sidebar */
#asset-search-root .sidebar {
  width: var(--sidebar-w); min-width: var(--sidebar-w);
  background: var(--surface); border-right: 1px solid var(--divider);
  padding: 28px 22px; overflow-y: auto;
  position: sticky; top: 56px; height: calc(100vh - 56px);
  display: flex; flex-direction: column; gap: 20px;
}
#asset-search-root .sidebar .sec-title {
  font-family: 'Spectral', serif; font-size: 16px; font-weight: 600;
  color: var(--text); letter-spacing: -.1px;
}
/* Facet group */
#asset-search-root .facet-group { display: flex; flex-direction: column; margin-bottom: 2px }
#asset-search-root .facet-group .fg-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 7px 8px; cursor: pointer; border-radius: 4px;
  transition: background .12s; user-select: none;
}
#asset-search-root .facet-group .fg-header:hover { background: var(--surface-hover) }
#asset-search-root .facet-group .fg-label {
  font-size: 13px; font-weight: 600; color: var(--text);
  text-transform: uppercase; letter-spacing: .4px;
}
#asset-search-root .facet-group .fg-count { font-size: 12px; color: var(--text-muted); margin-left: auto; margin-right: 6px }
#asset-search-root .facet-group .fg-arrow { font-size: 10px; color: var(--text-muted); transition: transform .2s; margin-left: 4px }
#asset-search-root .facet-group.open .fg-arrow { transform: rotate(90deg) }
#asset-search-root .facet-group .fg-body {
  max-height: 240px; overflow-y: auto; display: none; padding: 2px 0;
  scrollbar-width: thin; scrollbar-color: var(--divider) transparent;
}
#asset-search-root .facet-group .fg-body::-webkit-scrollbar { width: 4px }
#asset-search-root .facet-group .fg-body::-webkit-scrollbar-track { background: transparent }
#asset-search-root .facet-group .fg-body::-webkit-scrollbar-thumb { background: var(--divider); border-radius: 2px }
#asset-search-root .facet-group.open .fg-body { display: block }
#asset-search-root .facet-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 8px 5px 14px; border-radius: 4px; font-size: 13px;
  cursor: pointer; transition: background .12s;
}
#asset-search-root .facet-row:hover { background: var(--surface-hover) }
#asset-search-root .facet-row .fr-name {
  flex: 1; min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; color: var(--text-secondary);
}
#asset-search-root .facet-row .fr-name::before {
  content: ''; display: inline-block; width: 5px; height: 5px;
  border-radius: 50%; background: var(--divider); margin-right: 7px;
  vertical-align: middle; margin-top: -2px;
}
#asset-search-root .facet-row .fr-count { flex-shrink: 0; color: var(--text-muted); font-size: 12px; margin-left: 8px }
/* Main */
#asset-search-root .main { flex: 1; min-width: 0; padding: 24px 32px 48px; display: flex; flex-direction: column; gap: 16px }
/* Search row */
#asset-search-root .search-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap }
#asset-search-root .search-box {
  flex: 1; min-width: 300px; display: flex; background: var(--surface);
  border: 1px solid var(--divider); border-radius: var(--radius);
  overflow: hidden; transition: border-color .15s;
}
#asset-search-root .search-box:focus-within { border-color: var(--accent) }
#asset-search-root .search-box input {
  flex: 1; border: none; padding: 10px 16px; font-size: 15px;
  font-family: 'DM Sans', sans-serif; background: transparent;
  color: var(--text); outline: none;
}
#asset-search-root .search-box input::placeholder { color: var(--text-muted) }
#asset-search-root .search-box button {
  border: none; background: var(--accent); color: #fff; padding: 10px 20px;
  cursor: pointer; font-size: 14px; font-family: 'DM Sans', sans-serif;
  font-weight: 500; transition: opacity .15s;
}
#asset-search-root .search-box button:hover { opacity: .88 }
#asset-search-root .btn-soft {
  display: inline-flex; align-items: center; gap: 5px; padding: 8px 16px;
  border: 1px solid var(--divider); border-radius: var(--radius);
  background: var(--surface); color: var(--text-secondary); font-size: 13px;
  font-family: 'DM Sans', sans-serif; cursor: pointer; text-decoration: none;
  white-space: nowrap; transition: all .15s;
}
#asset-search-root .btn-soft:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-bg) }
#asset-search-root .btn-soft.active-view { background: var(--accent-bg); color: var(--accent); border-color: var(--accent) }
/* Result list */
#asset-search-root .result-list { display: flex; flex-direction: column; min-height: 200px }
#asset-search-root .r-item {
  background: var(--surface); border-bottom: 1px solid var(--divider);
  transition: background .15s;
}
#asset-search-root .r-item:first-child { border-radius: var(--radius) var(--radius) 0 0 }
#asset-search-root .r-item:last-child { border-radius: 0 0 var(--radius) var(--radius); border-bottom: none }
#asset-search-root .r-item:only-child { border-radius: var(--radius); border-bottom: none }
#asset-search-root .r-item:hover { background: var(--surface-hover) }
#asset-search-root .r-item.expanded { border-left: 3px solid var(--accent) }
/* Collapsed bar */
#asset-search-root .ri-bar {
  display: grid;
  grid-template-columns: 320px 80px 80px 1fr 24px;
  align-items: center; gap: 12px;
  padding: 14px 20px; cursor: pointer;
}
#asset-search-root .ri-bar .ri-ip {
  font-weight: 600; font-size: 15px; color: var(--accent);
  display: flex; align-items: center; gap: 4px;
  position: relative; flex-shrink: 0; min-width: 0;
}
#asset-search-root .ri-bar .ri-ip.ri-ip-vuln { color: #dc2626 }
#asset-search-root .ri-bar .ri-ip .ri-ip-text {
  max-width: 48ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
#asset-search-root .ri-bar .ri-ip .ri-actions { display: flex; gap: 2px; flex-shrink: 0; margin-left: auto }
#asset-search-root .ri-bar .ri-ip .ri-actions button {
  background: none; border: none; color: var(--text-muted); font-size: 13px;
  padding: 3px 5px; cursor: pointer; border-radius: 3px;
}
#asset-search-root .ri-bar .ri-ip .ri-actions button:hover { color: var(--accent); background: var(--accent-dim) }
/* IP tooltip */
#asset-search-root .ri-ip-tip {
  opacity: 0; pointer-events: none;
  position: absolute; bottom: calc(100% + 8px); left: 0;
  background: var(--text); color: var(--surface); font-size: 13px; font-weight: 400;
  padding: 8px 12px; border-radius: 6px; white-space: nowrap; z-index: 60;
  box-shadow: 0 4px 12px rgba(0,0,0,.15);
  display: flex; align-items: center; gap: 8px;
  transition: opacity .30s ease 0.1s;
}
#asset-search-root .ri-ip-tip::after {
  content: ''; position: absolute; top: 100%; left: 16px;
  border: 6px solid transparent; border-top-color: var(--text);
}
#asset-search-root .ri-ip-tip .tip-copy {
  background: none; border: none; color: var(--accent-dim); cursor: pointer;
  font-size: 13px; padding: 2px 4px;
}
#asset-search-root .ri-ip-tip .tip-copy:hover { color: var(--accent) }
#asset-search-root .ri-ip-text:hover ~ .ri-ip-tip,
#asset-search-root .ri-ip-tip:hover { opacity: 1; pointer-events: auto; transition: opacity .1s ease 0s }
#asset-search-root .ri-bar .ri-tag-cell { display: flex; justify-content: flex-start }
#asset-search-root .chip {
  font-size: 12px; font-weight: 500; padding: 3px 12px; border-radius: 4px;
  letter-spacing: .1px; white-space: nowrap;
}
#asset-search-root .chip-proto { background: #e0f2fe; color: #0369a1 }
#asset-search-root .chip-port { background: #dcfce7; color: #15803d }
#asset-search-root .ri-bar .ri-title {
  font-size: 15px; font-weight: 500; color: var(--text);
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  display: flex; align-items: center; gap: 8px;
}
#asset-search-root .ri-status-code {
  font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 3px;
  background: transparent; color: #0f766e; flex-shrink: 0; white-space: nowrap;
}
#asset-search-root .ri-sc-ok { background: #eaf0ef }
#asset-search-root .ri-uri-path {
  font-size: 11px; color: #0d9488; background: #f0fdfa; padding: 1px 7px;
  border-radius: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 260px; flex-shrink: 1;
}
#asset-search-root .ri-cert {
  font-size: 12px; color: var(--text-muted); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; flex-shrink: 1; min-width: 0; cursor: pointer;
}
#asset-search-root .ri-uri-wrap { position: relative; display: inline-block; vertical-align: middle }
#asset-search-root .ri-uri-tip {
  opacity: 0; pointer-events: none;
  position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
  background: var(--text); color: var(--surface); font-size: 13px; font-weight: 400;
  padding: 8px 12px; border-radius: 6px; white-space: nowrap; z-index: 60;
  box-shadow: 0 4px 12px rgba(0,0,0,.15);
  transition: opacity .30s ease 0.1s;
}
#asset-search-root .ri-uri-tip::after {
  content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
  border: 6px solid transparent; border-top-color: var(--text);
}
#asset-search-root .ri-uri-path:hover ~ .ri-uri-tip,
#asset-search-root .ri-uri-tip:hover { opacity: 1; pointer-events: auto; transition: opacity .1s ease 0s }
#asset-search-root .ri-bar .ri-chevron { font-size: 12px; color: var(--text-muted); transition: transform .2s; text-align: center }
#asset-search-root .r-item.expanded .ri-bar .ri-chevron { transform: rotate(90deg) }
/* Detail */
#asset-search-root .ri-detail { display: none; padding: 0 20px 20px; gap: 24px; align-items: stretch }
#asset-search-root .r-item.expanded .ri-detail { display: flex }
#asset-search-root .ri-detail .ri-col { flex: 1; min-width: 220px; display: flex; flex-direction: column; gap: 12px }
#asset-search-root .ri-detail .ri-col:first-child { flex: 0 1 280px; max-width: 320px }
#asset-search-root .ri-col-panel {
  flex: 1; display: flex; flex-direction: column; gap: 12px;
  padding: 6px 0 0; border: none; border-radius: 0; background: transparent; box-shadow: none;
}
#asset-search-root .ri-detail .ri-col h4 {
  font-family: 'Spectral', serif; font-size: 14px; font-weight: 600;
  color: var(--text); letter-spacing: -.1px;
  display: flex; align-items: baseline; gap: 8px;
}
#asset-search-root .meta-grid { display: grid; grid-template-columns: auto 1fr; gap: 5px 14px; font-size: 13px }
#asset-search-root .meta-grid .mg-k { color: var(--text-muted); white-space: nowrap }
#asset-search-root .meta-grid .mg-v { color: var(--text); word-break: break-all }
#asset-search-root .port-overview-list, #asset-search-root .vuln-overview-list { display: flex; flex-direction: column; gap: 10px }
#asset-search-root .port-overview-row, #asset-search-root .vuln-overview-card {
  border: 1px solid rgba(231,229,228,.36); border-radius: 10px;
  box-shadow: none; background: transparent;
}
#asset-search-root .port-overview-row {
  display: grid; grid-template-columns: auto minmax(0,1fr); align-items: stretch; overflow: hidden;
}
#asset-search-root .port-overview-main {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px; min-width: 0;
  border-right: 1px solid rgba(231,229,228,.28); background: transparent;
}
#asset-search-root .port-overview-proto, #asset-search-root .port-overview-port {
  display: inline-flex; align-items: center; justify-content: center;
  height: 28px; padding: 0 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
  background: rgba(41,37,36,.045); color: var(--text-secondary);
  border: 1px solid rgba(231,229,228,.9);
}
#asset-search-root .port-inline-btn {
  width: 28px; height: 28px; border: 1px solid rgba(231,229,228,.9);
  border-radius: 50%; background: rgba(255,255,255,.7); color: var(--text-secondary);
  cursor: pointer; transition: all .15s; flex-shrink: 0;
}
#asset-search-root .port-inline-btn:hover { background: rgba(13,148,136,.08); color: var(--accent); border-color: rgba(13,148,136,.18) }
#asset-search-root .port-overview-products {
  display: flex; align-items: center; gap: 6px; padding: 10px 12px;
  overflow-x: auto; overflow-y: hidden; min-width: 0; background: transparent;
  scrollbar-width: thin; scrollbar-color: rgba(168,162,158,.22) transparent;
}
#asset-search-root .port-overview-products::-webkit-scrollbar { height: 5px }
#asset-search-root .port-overview-products::-webkit-scrollbar-track { background: transparent }
#asset-search-root .port-overview-products::-webkit-scrollbar-thumb { background: rgba(168,162,158,.22); border-radius: 999px }
#asset-search-root .overview-product-chip {
  display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0;
  padding: 5px 10px; border-radius: 999px;
  background: rgba(41,37,36,.045); border: 1px solid rgba(231,229,228,.9);
  color: var(--text-secondary); font-size: 12px; font-weight: 500;
  cursor: pointer; transition: all .15s;
}
#asset-search-root .overview-product-chip:hover { background: rgba(13,148,136,.08); border-color: rgba(13,148,136,.16); color: var(--accent) }
#asset-search-root .overview-product-empty { font-size: 12px; color: var(--text-muted); white-space: nowrap }
#asset-search-root .vuln-overview-card { padding: 12px 14px }
#asset-search-root .vuln-overview-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px }
#asset-search-root .vuln-overview-text { min-width: 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap }
#asset-search-root .vuln-plugin-name { font-size: 13px; font-weight: 600; color: var(--text); word-break: break-word }
#asset-search-root .vuln-cve-chip {
  display: inline-flex; align-items: center; width: max-content; max-width: 100%;
  padding: 3px 9px; border-radius: 999px;
  background: rgba(41,37,36,.045); color: var(--text-secondary);
  font-size: 11px; font-weight: 600; border: 1px solid rgba(231,229,228,.9);
}
#asset-search-root .btn-html-view {
  font-size: 12px; background: none; border: 1px solid var(--divider);
  border-radius: 4px; padding: 4px 12px; cursor: pointer;
  color: var(--text-secondary); font-family: 'DM Sans', sans-serif;
  transition: all .15s; flex-shrink: 0; white-space: nowrap;
}
#asset-search-root .btn-html-view:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim) }
#asset-search-root .hdr-pre {
  background: #eaedf24d; border: none; border-radius: 4px;
  padding: 10px 14px; font-size: 12px; line-height: 1.7;
  max-height: 240px; max-width: 100%; overflow: auto;
  white-space: pre; font-family: inherit; color: var(--text-secondary); margin: 0;
  scrollbar-width: thin; scrollbar-color: var(--divider) transparent;
}
/* Pagination */
#asset-search-root .pag-row { display: flex; justify-content: center; padding: 20px 0; align-items: center; gap: 8px }
#asset-search-root .pag-inner { display: flex; gap: 4px; align-items: center; flex-wrap: wrap }
#asset-search-root .pag-inner a, #asset-search-root .pag-inner span {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 34px; height: 34px; padding: 0 10px; font-size: 13px;
  text-decoration: none; border-radius: var(--radius);
  background: var(--surface); border: 1px solid var(--divider);
  color: var(--text-secondary); font-family: 'DM Sans', sans-serif;
  transition: all .12s; cursor: pointer;
}
#asset-search-root .pag-inner a:hover { border-color: var(--accent); color: var(--accent) }
#asset-search-root .pag-inner .pag-disabled { opacity: .4; cursor: default; pointer-events: none }
#asset-search-root .pag-inner .pag-info { font-size: 13px; color: var(--text-muted); margin: 0 8px; cursor: default; border: none; background: none }
/* Loading / Empty */
#asset-search-root .loading-indicator { text-align: center; padding: 60px 0; color: var(--text-muted) }
#asset-search-root .loading-indicator i { font-size: 28px; margin-bottom: 8px; display: block }
#asset-search-root .empty-msg { text-align: center; padding: 80px 0; color: var(--text-muted); font-family: 'Spectral', serif; font-style: italic; font-size: 15px }
#asset-search-root .vuln-empty { font-size: 14px; color: var(--text-muted); padding: 8px 0; font-style: italic }
/* Toast */
#asset-search-root .toast {
  position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
  background: var(--text); color: var(--surface); padding: 10px 26px;
  border-radius: 24px; font-size: 13px; z-index: 999;
}
/* Modal */
#asset-search-root .modal-overlay {
  position: fixed; inset: 0; background: rgba(41,37,36,.25);
  z-index: 200; display: flex; align-items: center; justify-content: center;
}
#asset-search-root .modal-box {
  background: var(--surface); border-radius: var(--radius);
  padding: 28px; width: 400px; max-width: 90vw;
  box-shadow: 0 8px 30px rgba(0,0,0,.08);
}
#asset-search-root .modal-box h3 { font-family: 'Spectral', serif; font-size: 17px; margin-bottom: 18px; font-weight: 600 }
#asset-search-root .check-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 18px }
#asset-search-root .check-grid label { font-size: 14px; display: flex; align-items: center; gap: 6px; cursor: pointer; color: var(--text-secondary) }
#asset-search-root .modal-acts { display: flex; gap: 8px; justify-content: flex-end }
#asset-search-root .result-modal-box { width: min(760px, 92vw); padding: 0; overflow: hidden }
#asset-search-root .result-modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px; border-bottom: 1px solid var(--divider);
  background: var(--surface);
}
#asset-search-root .result-modal-head h3 { margin: 0; font-family: 'Spectral', serif; font-size: 18px }
#asset-search-root .result-modal-close { border: none; background: none; font-size: 20px; color: var(--text-muted); cursor: pointer }
#asset-search-root .result-modal-body { padding: 18px 22px; background: var(--surface) }
#asset-search-root .result-modal-pre {
  margin: 0; max-height: 62vh; overflow: auto;
  background: rgba(41,37,36,.94); color: #f5f3f0; border-radius: 8px;
  padding: 16px 18px; font-size: 12px; line-height: 1.7;
  white-space: pre-wrap; word-break: break-word;
  scrollbar-width: thin; scrollbar-color: rgba(245,243,240,.24) transparent;
}
/* Page size select */
#asset-search-root .page-size-select {
  font-family: 'DM Sans', sans-serif; font-size: 13px;
  border: 1px solid var(--divider); border-radius: 4px;
  padding: 4px 6px; background: var(--surface); color: var(--text);
  cursor: pointer;
}
#asset-search-root .jump-input {
  width: 50px; height: 30px; border-radius: 4px;
  border: 1px solid #d6d3d1; text-align: center; margin: 0 4px;
}
/* Responsive */
#asset-search-root .btn-soft.mobile-only { display: none }
@media(max-width:1024px) {
  #asset-search-root .sidebar { display: none }
  #asset-search-root .sidebar.mobile-open { display: flex; position: fixed; top: 56px; left: 0; bottom: 0; z-index: 100; box-shadow: 4px 0 20px rgba(0,0,0,.1); background: var(--surface) }
  #asset-search-root .btn-soft.mobile-only { display: inline-flex }
  #asset-search-root .main { padding: 16px 18px 32px }
  #asset-search-root .ri-bar { grid-template-columns: 220px 68px 68px 1fr 20px; gap: 8px; padding: 12px 16px }
}
@media(max-width:640px) {
  #asset-search-root .topbar { padding: 0 16px }
  #asset-search-root .topbar h1 { font-size: 16px }
  #asset-search-root .search-row { flex-direction: column; width: 100% }
  #asset-search-root .search-box { width: 100% }
  #asset-search-root .ri-bar { grid-template-columns: 1fr auto auto; padding: 12px 16px; gap: 4px 8px }
  #asset-search-root .ri-detail { flex-direction: column }
}
`

interface FacetCacheEntry {
  items: { name: string; count: number; favicon?: string }[]
  has_more: boolean
  next_offset: number
  count_label: string
  loading: boolean
}

export default function GlobalAssetSearchPage({ apiUrl, taskId }: { apiUrl: string; taskId?: number }) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const searchParams = new URLSearchParams(window.location.search)
  const [queryInput, setQueryInput] = useState(searchParams.get('search_data') ?? '')
  const [query, setQuery] = useState(searchParams.get('search_data') ?? '')
  const [cursor, setCursor] = useState(searchParams.get('cursor') ?? '')
  const [direction, setDirection] = useState(searchParams.get('dir') ?? 'next')
  const [rowsPerPage, setRowsPerPage] = useState(Number(searchParams.get('rows_per_page') ?? '13'))
  const [data, setData] = useState<TaskResultsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [viewExpanded, setViewExpanded] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [facetCache, setFacetCache] = useState<Record<string, FacetCacheEntry>>({})
  const [openFacets, setOpenFacets] = useState<Record<string, boolean>>({})
  const [portOverviewMap, setPortOverviewMap] = useState<Record<number, { rows: PortOverviewRow[]; total: number; hasMore: boolean; loading: boolean }>>({})
  const [vulnModal, setVulnModal] = useState<{ open: boolean; loading: boolean; data: VulnResultDetail | null }>({ open: false, loading: false, data: null })
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [exportFields, setExportFields] = useState<string[]>(['title', 'product', 'port', 'protocol', 'url', 'ip', 'uri_path', 'status_code', 'country'])
  const [exportLimit, setExportLimit] = useState<string>('1000')
  const [exportTaskName, setExportTaskName] = useState('')
  const [exportSubmitting, setExportSubmitting] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [toastMsg, setToastMsg] = useState('')
  const [dirscanKeys, setDirscanKeys] = useState<Record<string, boolean>>({})
  const [currentPage, setCurrentPage] = useState(1)
  const [exactTotal, setExactTotal] = useState<number | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [faviconItems, setFaviconItems] = useState<FaviconItem[]>([])
  const [faviconHasMore, setFaviconHasMore] = useState(false)
  const [faviconNextOffset, setFaviconNextOffset] = useState(0)
  const [faviconDeferred, setFaviconDeferred] = useState(false)
  const [zoneId, setZoneId] = useState<string>(searchParams.get('zone_id') ?? '')
  const [zones, setZones] = useState<ZoneItem[]>([])

  function loadZones() {
    get<{ zones: ZoneItem[] }>('/api/v1/zones').then((p) => setZones(p.zones || [])).catch(() => {})
  }
  useEffect(() => { loadZones() }, [])

  // 任务上下文中：首次加载时用任务所属 zone 做默认值，后续用户可自行切换
  useEffect(() => {
    if (!taskId || zoneId) return
    get<{ status: boolean; data: { zone_id: number } }>(`/api/v1/identify-tasks/${taskId}`)
      .then(p => {
        if (p.status && p.data?.zone_id) setZoneId(String(p.data.zone_id))
      })
      .catch(() => {})
  }, [taskId])

  // 切换区域后立刻重新搜索
  const prevZoneId = useRef(zoneId)
  useEffect(() => {
    if (zoneId !== prevZoneId.current && data) {
      loadResults()
    }
    prevZoneId.current = zoneId
  }, [zoneId])

  const faviconFetchRef = useRef(0)
  const facetVersionRef = useRef(0)
  const pageVersionRef = useRef(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // ── Toast ──
  function showToast(msg: string) {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(''), 2000)
  }

  // ── Load main results ──
  const loadResults = useCallback((overrides?: { q?: string; c?: string; d?: string; jump?: number }) => {
    const q = overrides?.q ?? query
    const c = overrides?.c ?? cursor
    const d = overrides?.d ?? direction
    const jump = overrides?.jump ?? 0
    const params = new URLSearchParams()
    if (q) params.set('search_data', q)
    if (c) params.set('cursor', c)
    if (d) params.set('dir', d)
    params.set('rows_per_page', String(rowsPerPage))
    if (jump) params.set('jump', String(jump))
    if (zoneId) params.set('zone_id', zoneId)
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)

    const requestVersion = ++pageVersionRef.current
    setLoading(true)
    setError('')
    get<TaskResultsResponse & { error?: string }>(`${apiUrl}?${params.toString()}`)
      .then((payload) => {
        if (requestVersion !== pageVersionRef.current) return
        if (payload.status !== 'ok') {
          setError((payload as TaskResultsResponse & { error?: string }).error ?? '结果加载失败')
          setData(null)
          return
        }
        setData(payload)
        if (payload.exact_total != null) setExactTotal(payload.exact_total)
        setFaviconItems(payload.favicon_items || [])
        setFaviconHasMore(!!payload.favicon_has_more)
        setFaviconNextOffset(payload.favicon_next_offset || 0)
        setFaviconDeferred(!!payload.favicon_deferred)
        if (payload.favicon_deferred) {
          fetchDeferredFavicon(q)
        }
        setError('')
      })
      .catch(() => {
        if (requestVersion !== pageVersionRef.current) return
        setError('结果加载失败')
        setData(null)
      })
      .finally(() => {
        if (requestVersion === pageVersionRef.current) setLoading(false)
      })
  }, [apiUrl, cursor, direction, query, rowsPerPage, zoneId])

  useEffect(() => {
    loadResults()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const facetBaseUrl = (data?.contract?.facet_endpoint as string) || '/api/v1/assets/facets'

  // ── Deferred favicon ──
  function fetchDeferredFavicon(search: string) {
    const version = ++faviconFetchRef.current
    get<TaskFacetResponse>(`${facetBaseUrl}?field=favicon&offset=0&search_data=${encodeURIComponent(search)}${zoneId ? '&zone_id=' + encodeURIComponent(zoneId) : ''}`)
      .then((payload) => {
        if (version !== faviconFetchRef.current) return
        if (payload.status !== 'ok') return
        setFaviconItems(payload.items || [])
        setFaviconHasMore(!!payload.has_more)
        setFaviconNextOffset(payload.next_offset || 0)
        setFaviconDeferred(false)
      })
      .catch(() => {})
  }

  function loadMoreFavicon() {
    const offset = faviconNextOffset || faviconItems.length
    get<TaskFacetResponse>(`${facetBaseUrl}?field=favicon&offset=${offset}&search_data=${encodeURIComponent(query)}${zoneId ? '&zone_id=' + encodeURIComponent(zoneId) : ''}`)
      .then((payload) => {
        if (payload.status !== 'ok') return
        setFaviconItems(prev => [...prev, ...(payload.items || [])])
        setFaviconHasMore(!!payload.has_more)
        setFaviconNextOffset(payload.next_offset || 0)
      })
      .catch(() => {})
  }

  // ── Facets ──
  function fetchFacet(field: string, offset: number, append: boolean) {
    const version = facetVersionRef.current
    setFacetCache(prev => {
      const entry = prev[field] || { items: [], has_more: false, next_offset: 0, count_label: '…', loading: false }
      if (entry.loading) return prev
      return { ...prev, [field]: { ...entry, loading: true } }
    })

    get<TaskFacetResponse>(`${facetBaseUrl}?field=${field}&offset=${offset}&search_data=${encodeURIComponent(query)}${zoneId ? '&zone_id=' + encodeURIComponent(zoneId) : ''}`)
      .then((payload) => {
        if (version !== facetVersionRef.current) return
        setFacetCache(prev => {
          const old = prev[field]
          const items = append ? [...(old?.items || []), ...(payload.items || [])] : (payload.items || [])
          return {
            ...prev,
            [field]: {
              items,
              has_more: !!payload.has_more,
              next_offset: payload.next_offset || items.length,
              count_label: payload.count_label || String(items.length),
              loading: false,
            },
          }
        })
      })
      .catch(() => {
        if (version !== facetVersionRef.current) return
        setFacetCache(prev => ({ ...prev, [field]: { ...prev[field], loading: false } }))
      })
  }

  function toggleFacet(field: string) {
    const wasOpen = openFacets[field]
    const nowOpen = !wasOpen
    setOpenFacets(prev => ({ ...prev, [field]: nowOpen }))
    if (!nowOpen) return
    if (!facetCache[field]) {
      setFacetCache(prev => ({ ...prev, [field]: { items: [], has_more: false, next_offset: 0, count_label: '…', loading: false } }))
      fetchFacet(field, 0, false)
    }
  }

  function refreshAllFacets() {
    const version = ++facetVersionRef.current
    const newCache: Record<string, FacetCacheEntry> = {}
    const toFetch: string[] = []
    Object.keys(openFacets).forEach(field => {
      if (openFacets[field]) {
        newCache[field] = { items: [], has_more: false, next_offset: 0, count_label: '…', loading: false }
        toFetch.push(field)
      }
    })
    setFacetCache(newCache)
    toFetch.forEach(field => {
      get<TaskFacetResponse>(`${facetBaseUrl}?field=${field}&offset=0&search_data=${encodeURIComponent(query)}`)
        .then((payload) => {
          if (version !== facetVersionRef.current) return
          setFacetCache(prev => ({
            ...prev,
            [field]: {
              items: payload.items || [],
              has_more: !!payload.has_more,
              next_offset: payload.next_offset || 0,
              count_label: payload.count_label || '0',
              loading: false,
            },
          }))
        })
        .catch(() => {})
    })
  }

  // ── Search / Pagination ──
  function doSearch() {
    setQuery(queryInput)
    setCursor('')
    setDirection('next')
    setCurrentPage(1)
    setExpandedIds(new Set())
    setOpenFacets({})
    setFacetCache({})
    facetVersionRef.current++
    loadResults({ q: queryInput, c: '', d: 'next' })
    // Reset facet cache on next render
    setTimeout(() => refreshAllFacets(), 100)
  }

  function handleSearchInputChange(next: string) {
    setQueryInput(next)
    setQuery(next)
    setCursor('')
    setDirection('next')
    setCurrentPage(1)
    setExpandedIds(new Set())
    setOpenFacets({})
    setFacetCache({})
    facetVersionRef.current++
    loadResults({ q: next, c: '', d: 'next' })
    setTimeout(() => refreshAllFacets(), 100)
  }

  function goPage(nextCursor: string, nextDirection: 'next' | 'prev', jump?: number) {
    if (!nextCursor && !nextDirection && !jump) return
    if (!jump) {
      setCurrentPage(prev => {
        const next = prev + (nextDirection === 'prev' ? -1 : 1)
        return next < 1 ? 1 : next
      })
    }
    setCursor(nextCursor)
    setDirection(nextDirection)
    setExpandedIds(new Set())
    loadResults({ c: nextCursor, d: nextDirection, jump })
    setTimeout(() => window.scrollTo(0, 0), 0)
  }

  function jumpPage(n: number) {
    const totalDisplay = data?.exact_total ?? data?.estimated_total ?? 0
    const totalPages = Math.max(1, Math.ceil(totalDisplay / rowsPerPage))
    const targetPage = Math.min(Math.max(currentPage + n, 1), totalPages)
    const clampedN = targetPage - currentPage
    if (clampedN === 0) return
    setCurrentPage(prev => prev + clampedN)
    if (clampedN > 0) {
      goPage(data?.next_cursor || data?.prev_cursor || '', 'next', Math.abs(clampedN))
    } else {
      goPage(data?.prev_cursor || data?.next_cursor || '', 'prev', Math.abs(clampedN))
    }
  }

  function jumpToPage() {
    const inp = document.getElementById('jumpPageInput') as HTMLInputElement
    if (!inp) return
    const target = parseInt(inp.value, 10)
    if (!target || target < 1) return
    const totalDisplay = data?.exact_total ?? data?.estimated_total ?? 0
    const totalPages = Math.max(1, Math.ceil(totalDisplay / rowsPerPage))
    const page = Math.min(target, totalPages)
    const delta = page - currentPage
    if (delta === 0) return
    const n = Math.abs(delta) > JUMP_PAGES ? (delta > 0 ? JUMP_PAGES : -JUMP_PAGES) : delta
    jumpPage(n)
  }

  function changePageSize(size: number) {
    setRowsPerPage(size)
    setCursor('')
    setDirection('next')
    setCurrentPage(1)
    loadResults({ c: '', d: 'next' })
  }

  // ── Toggle expand ──
  function toggleResult(id: number) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function toggleViewMode() {
    setViewExpanded(prev => { setExpandedIds(new Set()); return !prev })
  }

  // 展开资产时异步查询是否有目录扫描结果
  useEffect(() => {
    const rs = data?.results || []
    const targets = viewExpanded ? rs : rs.filter(r => expandedIds.has(r.id))
    targets.forEach(item => {
      if (!item.host || !item.port) return
      const key = `${item.protocol}:${item.host}:${item.port}`
      if (dirscanKeys.hasOwnProperty(key)) return
      get<{ status: string; has_dirscan: boolean }>(
        `/api/v1/assets/dirscan-results?host=${encodeURIComponent(item.host)}&port=${item.port}&protocol=${encodeURIComponent(item.protocol)}&check_only=true`
      ).then(res => {
        if (res.status === 'ok') {
          setDirscanKeys(prev => ({ ...prev, [key]: res.has_dirscan }))
        }
      }).catch(() => {})
    })
  }, [expandedIds, viewExpanded, data?.results])

  // ── Facet click ──
  function applyFacet(field: string, value: string) {
    // "(空)" 表示字段为空（null 或空字符串），用 !field:"*" 搜索
    const term = value === '(空)' ? `!${field}:"*"` : `${field}:"${value}"`
    const next = queryInput ? `${queryInput} && ${term}` : term
    setQueryInput(next)
    handleSearchInputChange(next)
  }

  // ── Port overview ──
  function loadPortOverview(resultId: number, ip: string, target: string) {
    setPortOverviewMap(prev => ({ ...prev, [resultId]: { rows: [], total: 0, hasMore: false, loading: true } }))
    get<PortOverviewResponse>(`/api/v1/assets/port-overview?ip=${encodeURIComponent(ip)}&offset=0&limit=20&current_target=${encodeURIComponent(target)}`)
      .then((payload) => {
        if (payload.status !== 'ok') throw new Error('API error')
        setPortOverviewMap(prev => ({ ...prev, [resultId]: { rows: payload.rows, total: payload.total, hasMore: payload.has_more, loading: false } }))
      })
      .catch(() => setPortOverviewMap(prev => ({ ...prev, [resultId]: { rows: [], total: 0, hasMore: false, loading: false } })))
  }

  function loadMorePortOverview(resultId: number, ip: string, target: string) {
    const current = portOverviewMap[resultId]
    if (!current || current.loading) return
    const offset = current.rows.length
    setPortOverviewMap(prev => ({ ...prev, [resultId]: { ...current, loading: true } }))
    get<PortOverviewResponse>(`/api/v1/assets/port-overview?ip=${encodeURIComponent(ip)}&offset=${offset}&limit=20&current_target=${encodeURIComponent(target)}`)
      .then((payload) => {
        if (payload.status !== 'ok') throw new Error('API error')
        setPortOverviewMap(prev => {
          const prevItem = prev[resultId]
          return { ...prev, [resultId]: { rows: [...(prevItem?.rows || []), ...payload.rows], total: payload.total, hasMore: payload.has_more, loading: false } }
        })
      })
      .catch(() => setPortOverviewMap(prev => ({ ...prev, [resultId]: { ...prev[resultId], loading: false } })))
  }


  // ── Vuln modal ──
  function openVulnResult(vulnId: number) {
    setVulnModal({ open: true, loading: true, data: null })
    get<VulnResultDetail>(`/api/v1/identify-results/${vulnId}/vuln-result`)
      .then((payload) => {
        if (payload.status !== 'ok') throw new Error('vuln result error')
        setVulnModal({ open: true, loading: false, data: payload })
      })
      .catch(() => setVulnModal({ open: true, loading: false, data: null }))
  }

  // ── Export ──
  function submitExport() {
    if (!exportFields.length) { alert('请至少选择一个导出字段'); return }
    let limitVal = exportLimit
    const selectEl = document.getElementById('exportLimitSelect') as HTMLSelectElement
    if (selectEl && selectEl.value === 'all') limitVal = ''
    let exportLimitNum: number | null = null
    if (limitVal !== 'all' && limitVal !== '') {
      const n = parseInt(limitVal, 10)
      if (isNaN(n) || n < 1 || n > 50000) { alert('导出条数需在 1–50000 之间'); return }
      exportLimitNum = n
    }

    setExportSubmitting(true)
    const hasVuln = exportFields.includes('vuln')
    post<{ status: string; error?: string; export_task_id?: number }>('/api/v1/assets/export', {
        fields: exportFields,
        export_limit: exportLimitNum,
        search_string: new URLSearchParams(window.location.search).get('search_data') || '',
        task_type: 'global',
        task_id: null,
        task_name: exportTaskName,
        zone_id: zoneId || null,
        include_vuln_result: hasVuln,
      })
      .then((data) => {
        setExportSubmitting(false)
        if (data.status !== 'ok') { alert(data.error || '提交失败'); return }
        setExportModalOpen(false)
        showToast(`导出任务已提交（#${data.export_task_id}），请在导出任务页查看`)
      })
      .catch(() => {
        setExportSubmitting(false)
        alert('网络错误')
      })
  }

  // ── Copy / Redirect ──
  function copyContent(text: string) {
    copyToClipboard(text).then((ok) => {
      if (ok) showToast('已复制到剪贴板')
    })
  }

  function redirectToURL(url: string) {
    window.open(url, '_blank')
  }

  // ── Helpers ──
  function escHtml(s: string) {
    const div = document.createElement('div')
    div.textContent = s
    return div.innerHTML
  }

  // ── Derived state ──
  const { totalDisplay, totalPages, totalLabel, results, expandedSet } = useMemo(() => {
    const td = data?.exact_total ?? exactTotal ?? data?.estimated_total ?? 0
    const tp = Math.max(1, Math.ceil(td / rowsPerPage))
    const tl = (data?.exact_total ?? exactTotal) != null ? '' : '约 '
    const rs = data?.results || []
    const es = viewExpanded ? new Set(rs.map(r => r.id)) : expandedIds
    return { totalDisplay: td, totalPages: tp, totalLabel: tl, results: rs, expandedSet: es }
  }, [data?.exact_total, data?.estimated_total, exactTotal, rowsPerPage, viewExpanded, expandedIds, data?.results])

  // ── Render ──
  return (
    <>
      {/* Flag CSS */}
      <link rel="stylesheet" href="/static/css/flag.css" />

      <style>{STYLES}</style>

      <div id="asset-search-root">
        {/* Top bar */}
        <div className="topbar">
          <h1><em>{data?.task_name || '全局资产'}</em> 识别结果</h1>
          <div className="meta">
            <span className="pill">匹配{data?.exact_total == null ? '约 ' : ' '}{totalDisplay.toLocaleString()} 条</span>
            <button type="button" className="btn-soft" style={{ marginLeft: 8, fontWeight: 500 }} onClick={() => setHelpOpen(true)}>
              <i className="fa fa-question-circle" style={{ marginRight: 4 }} />说明
            </button>
          </div>
        </div>

        <div className="shell">
          {/* Sidebar */}
          <aside className={`sidebar${sidebarOpen ? ' mobile-open' : ''}`}>
            <div>
              <div className="sec-title" style={{ marginBottom: 12 }}>聚类统计</div>
              {ALL_FACET_FIELDS.map(field => {
                const cached = facetCache[field]
                const isOpen = !!openFacets[field]
                return (
                  <div key={field} className={`facet-group${isOpen ? ' open' : ''}`}>
                    <div className="fg-header" onClick={() => toggleFacet(field)}>
                      <span className="fg-label">{FACET_LABELS[field] || field.toUpperCase()}</span>
                      <span className="fg-count" style={!cached ? { color: '#c0bdb8' } : undefined}>
                        {cached ? cached.count_label : '…'}
                      </span>
                      <span className="fg-arrow">&#9656;</span>
                    </div>
                    <div className="fg-body">
                      {cached && cached.items.length > 0 ? (
                        <>
                          {cached.items.map(item => (
                            <div key={item.name} className="facet-row" onClick={() => applyFacet(field, item.name)}>
                              <span className="fr-name" title={item.name}>{item.name}</span>
                              <span className="fr-count">{item.count}</span>
                            </div>
                          ))}
                          {cached.has_more && (
                            <div className="facet-row" style={{ justifyContent: 'center', paddingLeft: 8 }}>
                              <button type="button" className="btn-soft" onClick={(e) => { e.stopPropagation(); fetchFacet(field, cached.next_offset, true) }}>
                                更多
                              </button>
                            </div>
                          )}
                        </>
                      ) : cached && cached.loading ? (
                        <div className="vuln-empty">加载中…</div>
                      ) : cached && !cached.loading && cached.items.length === 0 ? (
                        <div className="vuln-empty">无数据</div>
                      ) : (
                        <div className="vuln-empty">点击展开加载…</div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </aside>

          {/* Main */}
          <main className="main">
            {/* Search row */}
            <div className="search-row">
              <div className="search-box" style={{ flex: 1 }}>
                <input
                  ref={inputRef}
                  type="text"
                  value={queryInput}
                  onChange={(e) => setQueryInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') doSearch() }}
                  placeholder='ip:"1.2.3.4" host:"example.com" port:"80" protocol:"http" title:"网站名" product:"nginx" body:"关键词" html:"<div" header:"Server" vuln:"漏洞名" cve:"CVE-2024" favicon:"hash" cert:"CN名" cert_org:"组织" cert_serial:"序列号" country:"中国" province:"北京" city:"北京" isp:"电信" copyright:"版权" icp:"备案号" uri_path:"/api" status_code:"200" ipc:"1.2.0.0/16"'
                />
                <button type="button" onClick={doSearch}><i className="fa fa-search" /></button>
              </div>
              <button type="button" className="btn-soft mobile-only" onClick={() => setSidebarOpen(o => !o)}>
                <i className="fa fa-th-list" /> 面板
              </button>
              <button type="button" className={`btn-soft${viewExpanded ? ' active-view' : ''}`} onClick={toggleViewMode}>
                <i className={`fa fa-${viewExpanded ? 'expand' : 'compress'}`} /> {viewExpanded ? '收起全部' : '展开全部'}
              </button>
              {canWrite && <button type="button" className="btn-soft" onClick={() => { setExportTaskName(''); setExportModalOpen(true) }}>
                <i className="fa fa-download" /> 导出
              </button>}
              <Select
                value={zoneId || undefined}
                onChange={(v: string) => { setZoneId(v || ''); }}
                style={{
                  width: 140,
                  background: 'var(--surface)',
                  borderColor: 'var(--divider)',
                  borderRadius: 'var(--radius)',
                  fontSize: 13,
                  color: 'var(--text-secondary)',
                }}
                placeholder="全部区域"
                allowClear
              >
                <Select.Option key="__intranet__" value="__intranet__">所有内网</Select.Option>
                {zones.map(z => <Select.Option key={z.id} value={String(z.id)}>{z.name}</Select.Option>)}
              </Select>
              {canWrite && taskId != null && (
                <a className="btn-soft" href={`/api/v1/identify-tasks/result/download?uid=${taskId}&search_data=${encodeURIComponent(new URLSearchParams(window.location.search).get('search_data') || '')}&zone_id=${encodeURIComponent(zoneId || '')}`} target="_blank" rel="noreferrer">
                  <i className="fa fa-download" /> 快导
                </a>
              )}
            </div>

            {/* Favicon strip */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginTop: -4 }}>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>favicon：</span>
              {faviconItems.length > 0 ? (
                <>
                  {faviconItems.map(item => (
                    <button key={item.name} type="button" className="btn-soft" style={{ padding: '6px 10px' }}
                      onClick={() => applyFacet('favicon', item.name)} title={item.name}>
                      {item.favicon ? <img src={item.favicon} alt="favicon" style={{ width: 16, height: 16, borderRadius: 3, objectFit: 'cover' }} /> : <i className="fa fa-image" />}
                      <span>{item.count}</span>
                    </button>
                  ))}
                  {faviconHasMore && <button type="button" className="btn-soft" onClick={loadMoreFavicon}>更多</button>}
                </>
              ) : (
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>暂无</span>
              )}
            </div>

            {/* Result list */}
            <div className="result-list" style={loading && data ? { opacity: 0.4 } : undefined}>
              {loading && !data ? (
                <div className="loading-indicator" style={{ display: 'block' }}>
                  <i className="fa fa-spinner" style={{ animation: 'spin .8s linear infinite' }} />
                  <span>加载中…</span>
                </div>
              ) : error ? (
                <div className="empty-msg" style={{ color: '#dc2626' }}>{error}</div>
              ) : results.length === 0 ? (
                <div className="empty-msg">没有匹配的识别结果</div>
              ) : (
                results.map(item => {
                  const expanded = expandedSet.has(item.id)
                  const certFull = (item.cert_org || item.cert_org_unit)
                    ? [item.cert_org || '', item.cert_org_unit || ''].join(' / ').replace(/^ \/ | \/ $/g, '')
                    : ''
                  const certSearchVal = item.cert_org || item.cert_org_unit || ''
                  const po = portOverviewMap[item.id]
                  const hasVulns = item.related_vulns && item.related_vulns.length > 0

                  return (
                    <div key={item.id} id={`r${item.id}`} className={`r-item${expanded ? ' expanded' : ''}`}>
                      <div className="ri-bar" onClick={() => toggleResult(item.id)}>
                        <span className={`ri-ip${hasVulns ? ' ri-ip-vuln' : ''}`}>
                          <span className="ri-ip-text">{item.host || item.ip}</span>
                          <span className="ri-ip-tip">
                            {item.host || item.ip}
                            <button className="tip-copy" onClick={(e) => { e.stopPropagation(); copyContent(item.target) }}>复制</button>
                          </span>
                          <span className="ri-actions">
                            <button onClick={(e) => { e.stopPropagation(); copyContent(item.target) }} title="复制URL"><i className="fa fa-copy" /></button>
                            <button onClick={(e) => { e.stopPropagation(); redirectToURL(item.target) }} title={`打开 ${item.target}`}><i className="fa fa-external-link" /></button>
                          </span>
                        </span>
                        <span className="ri-tag-cell"><span className="chip chip-proto">{item.protocol}</span></span>
                        <span className="ri-tag-cell"><span className="chip chip-port">{item.port}</span></span>
                        <span className="ri-title">
                          {item.title || '—'}
                          {item.status_code ? <span className={`ri-status-code${item.status_code === 200 ? ' ri-sc-ok' : ''}`}>{item.status_code}</span> : null}
                          {item.uri_path ? (
                            <span className="ri-uri-wrap">
                              <span className="ri-uri-path">{item.uri_path}</span>
                              <span className="ri-uri-tip">{item.uri_path}</span>
                            </span>
                          ) : null}
                          {certFull ? (
                            <span className="ri-cert" onClick={(e) => { e.stopPropagation(); applyFacet('cert', certSearchVal) }} title={certFull}>
                              {certFull}
                            </span>
                          ) : null}
                        </span>
                        <span className="ri-chevron">&#9656;</span>
                      </div>

                      <div className="ri-detail">
                        {/* Col 1: Basic info */}
                        <div className="ri-col">
                          <h4>基础信息</h4>
                          <div className="meta-grid">
                            {(item.country && item.country !== 'None') || item.province || item.city ? (
                              <>
                                <span className="mg-k">地区</span>
                                <span className="mg-v">
                                  {item.country_code ? <span className={`c-flag c-flag--${item.country_code}`} /> : null}
                                  {' '}{item.country && item.country !== 'None' ? item.country : ''}
                                  {item.province ? ` / ${item.province}` : ''}
                                  {item.city ? ` / ${item.city}` : ''}
                                </span>
                              </>
                            ) : null}
                            {item.isp ? (
                              <>
                                <span className="mg-k">运营商</span>
                                <span className="mg-v">
                                  <span style={{ cursor: 'pointer', color: '#0d9488' }} onClick={() => applyFacet('isp', item.isp)}>{item.isp}</span>
                                </span>
                              </>
                            ) : null}
                            <span className="mg-k">IP</span>
                            <span className="mg-v">{item.ip}</span>
                            {item.zone_name ? (
                              <>
                                <span className="mg-k">区域</span>
                                <span className="mg-v">{item.zone_name}</span>
                              </>
                            ) : null}
                            <span className="mg-k">当前端口</span>
                            <span className="mg-v">{item.protocol} / {item.port}</span>
                            {item.favicon_md5 ? (
                              <>
                                <span className="mg-k">favicon</span>
                                <span className="mg-v">
                                  {item.favicon ? <img src={item.favicon} alt="favicon" style={{ width: 16, height: 16, borderRadius: 3, objectFit: 'cover', verticalAlign: 'middle', marginRight: 6 }} /> : null}
                                  <span style={{ cursor: 'pointer', color: '#0d9488' }} onClick={() => applyFacet('favicon', item.favicon_md5)}>{item.favicon_md5}</span>
                                </span>
                              </>
                            ) : null}
                            {item.cert_serial ? (
                              <>
                                <span className="mg-k">证书序列号</span>
                                <span className="mg-v">
                                  <span style={{ cursor: 'pointer', color: '#0d9488' }} onClick={() => applyFacet('cert_serial', item.cert_serial)}>{item.cert_serial}</span>
                                </span>
                              </>
                            ) : null}
                            {item.cert_common_name ? (
                              <>
                                <span className="mg-k">证书主体</span>
                                <span className="mg-v">
                                  <span style={{ cursor: 'pointer', color: '#0d9488' }} onClick={() => applyFacet('cert', item.cert_common_name)}>{item.cert_common_name}</span>
                                </span>
                              </>
                            ) : null}
                            <span className="mg-k">URI路径</span>
                            <span className="mg-v">
                              {item.uri_path ? (
                                <span style={{ cursor: 'pointer', color: '#0d9488' }} onClick={() => applyFacet('uri_path', item.uri_path)}>{item.uri_path}</span>
                              ) : '—'}
                            </span>
                            <span className="mg-k">时间</span>
                            <span className="mg-v">{item.creatime || ''}</span>
                          </div>
                          <h4 style={{ marginTop: 4 }}>完整响应{' '}
                            <button className="btn-html-view" onClick={() => window.open(`/api/v1/identify-results/${item.id}/html`, '_blank')}>
                              <i className="fa fa-code" /> 查看 HTML
                            </button>
                          </h4>
                        </div>

                        {/* Col 2: Port overview */}
                        <div className="ri-col" style={{ flex: 1.3 }}>
                          <div className="ri-col-panel">
                            <h4>
                              <span>端口概览</span>
                              <Button type="link" size="small"
                                onClick={() => { const p = new URLSearchParams({ ip: item.ip }); window.open(`/react-shell/ip-detail?${p.toString()}`, '_blank') }}
                                style={{ fontSize: 13 }}
                              >同IP端口详情</Button>
                              {dirscanKeys[`${item.protocol}:${item.host}:${item.port}`] && (
                                <Button type="link" size="small"
                                  onClick={() => window.open(`/react-shell/dirscan-results?host=${encodeURIComponent(item.host)}&port=${item.port}&protocol=${encodeURIComponent(item.protocol)}`, '_blank')}
                                  style={{ marginLeft: 12, fontSize: 13 }}
                                >目录扫描</Button>
                              )}
                            </h4>
                            <div className="port-overview-list">
                              {/* Current port row always shown */}
                              <div className="port-overview-row">
                                <div className="port-overview-main">
                                  <span className="port-overview-proto">{item.protocol}</span>
                                  <span className="port-overview-port">{item.port}</span>
                                </div>
                                <div className="port-overview-products">
                                  {item.product.length > 0 ? item.product.map(p => (
                                    <span key={p} className="overview-product-chip" onClick={() => applyFacet('product', p)}>{p}</span>
                                  )) : <span className="overview-product-empty">未识别产品</span>}
                                </div>
                              </div>
                              {/* Loaded port overview rows (exclude current port already rendered above) */}
                              {po && po.rows.filter(row => !row.is_current).map((row, idx) => (
                                <div key={idx} className="port-overview-row">
                                  <div className="port-overview-main">
                                    <span className="port-overview-proto">{row.protocol}</span>
                                    <span className="port-overview-port">{row.port}</span>
                                  </div>
                                  <div className="port-overview-products">
                                    {(row.products || []).length > 0 ? row.products.map(p => (
                                      <span key={p} className="overview-product-chip" onClick={() => applyFacet('product', p)}>{p}</span>
                                    )) : <span className="overview-product-empty">未识别产品</span>}
                                  </div>
                                </div>
                              ))}
                            </div>
                            {po && po.loading ? (
                              <span style={{ fontSize: 13, color: 'var(--text-muted)', padding: '6px 0' }}>加载中…</span>
                            ) : !po || po.hasMore ? (
                              <button type="button" className="btn-soft" style={{ marginTop: 6, width: '100%' }}
                                onClick={() => {
                                  if (!po) loadPortOverview(item.id, item.ip, item.target)
                                  else loadMorePortOverview(item.id, item.ip, item.target)
                                }}
                              >
                                {!po ? (
                                  <><i className="fa fa-chevron-down" /> 查看同 IP 其他资产</>
                                ) : (
                                  <><i className="fa fa-chevron-down" /> 展开更多（已加载 {po.rows.length} / 共 {po.total} 项）</>
                                )}
                              </button>
                            ) : null}
                          </div>
                        </div>

                        {/* Col 3: Vulns */}
                        {hasVulns ? (
                          <div className="ri-col" style={{ flex: 0.95 }}>
                            <div className="ri-col-panel">
                              <h4>受影响漏洞</h4>
                              <div className="vuln-overview-list">
                                {item.related_vulns.map(vuln => (
                                  <div key={vuln.id} className="vuln-overview-card">
                                    <div className="vuln-overview-head">
                                      <div className="vuln-overview-text">
                                        <div className="vuln-plugin-name">{vuln.plugin_name || '未命名漏洞'}</div>
                                        {vuln.cve ? <div className="vuln-cve-chip">{vuln.cve}</div> : null}
                                      </div>
                                      <div style={{ display: 'flex', gap: 6 }}>
                                        {canWrite && vuln.exp_id != null ? (
                                          <button type="button" className="btn-html-view"
                                            onClick={(e) => { e.stopPropagation(); window.open(`/react-shell/vuln-exploit?target=${encodeURIComponent(item.target)}&exp_id=${vuln.exp_id}`, '_blank') }}
                                          >
                                            <i className="fa fa-bolt" /> 利用
                                          </button>
                                        ) : null}
                                        <button type="button" className="btn-html-view" onClick={() => openVulnResult(vuln.id)}>
                                          <i className="fa fa-file-text-o" /> 结果
                                        </button>
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        ) : null}

                        {/* Col 4: Response headers */}
                        <div className="ri-col" style={{ flex: '0 0 280px', minWidth: 200 }}>
                          <h4>响应头</h4>
                          <pre className="hdr-pre">{item.header || ''}</pre>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>

            {loading && data && (
              <div className="loading-indicator" style={{ display: 'block', padding: '20px 0' }}>
                <i className="fa fa-spinner" style={{ animation: 'spin .8s linear infinite' }} />
                <span>加载中…</span>
              </div>
            )}

            {/* Pagination */}
            {data && !loading && (
              <div className="pag-row">
                <div className="pag-inner">
                  <span className="pag-info">
                    第 <strong>{currentPage}</strong> / {totalLabel}{totalPages.toLocaleString()} 页（{totalDisplay.toLocaleString()} 条）
                  </span>
                  <input type="number" id="jumpPageInput" min={1} max={totalPages} placeholder="页"
                    className="jump-input"
                    onKeyDown={(e) => { if (e.key === 'Enter') jumpToPage() }} />
                  <a href="javascript:void(0)" onClick={jumpToPage} style={{ margin: '0 4px' }}>跳转</a>
                  {data.has_prev ? (
                    <>
                      <a href="javascript:void(0)" onClick={() => jumpPage(-JUMP_PAGES)} style={{ margin: '0 2px', fontSize: 12, color: '#78716c' }}>
                        ←{JUMP_PAGES}页
                      </a>
                      <a href="javascript:void(0)" onClick={() => goPage(data.prev_cursor, 'prev')} style={{ margin: '0 4px' }}>
                        ← 上一页
                      </a>
                    </>
                  ) : (
                    <span className="pag-disabled">← 上一页</span>
                  )}
                  {data.has_next ? (
                    <>
                      <a href="javascript:void(0)" onClick={() => goPage(data.next_cursor, 'next')} style={{ margin: '0 4px' }}>
                        下一页 →
                      </a>
                      <a href="javascript:void(0)" onClick={() => jumpPage(JUMP_PAGES)} style={{ margin: '0 2px', fontSize: 12, color: '#78716c' }}>
                        {JUMP_PAGES}页→
                      </a>
                    </>
                  ) : (
                    <span className="pag-disabled">下一页 →</span>
                  )}
                </div>
                <span style={{ marginLeft: 12 }}>
                  每页{' '}
                  <select className="page-size-select" value={rowsPerPage} onChange={(e) => changePageSize(Number(e.target.value))}>
                    <option value={13}>13</option>
                    <option value={5}>5</option>
                    <option value={10}>10</option>
                    <option value={100}>100</option>
                    <option value={1000}>1000</option>
                  </select>{' '}
                  条
                </span>
              </div>
            )}
          </main>
        </div>

        {/* Export Modal */}
        {exportModalOpen && (
          <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setExportModalOpen(false) }}>
            <div className="modal-box" style={{ width: 520 }}>
              <h3>导出 CSV</h3>
              <div className="check-grid">
                {[
                  ['title', '标题'], ['product', '产品'], ['ipc', 'IP段'], ['country', '地区'],
                  ['province', '省份'], ['city', '城市'], ['isp', '运营商'], ['port', '端口'],
                  ['protocol', '协议'], ['status_code', '状态码'], ['uri_path', 'URI路径'], ['url', 'URL'],
                  ['host', '主机名'], ['ip', 'IP地址'], ['favicon_md5', 'favicon MD5'], ['cert_org', '证书组织'],
                  ['cert_common_name', '证书主体'], ['cert_serial', '证书序列号'], ['vuln', '漏洞名称'],
                  ['cve', 'CVE编号'],
                ].map(([val, label]) => (
                  <label key={val}>
                    <input type="checkbox" value={val} checked={exportFields.includes(val)}
                      onChange={(e) => {
                        if (e.target.checked) setExportFields(prev => [...prev, val])
                        else setExportFields(prev => prev.filter(f => f !== val))
                      }} />
                    {label}
                  </label>
                ))}
              </div>
              {exportFields.includes('vuln') && (
                <div style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 14, padding: '6px 10px', background: '#fef3c7', borderRadius: 4 }}>
                  勾选了"漏洞名称"，将同时导出漏洞验证结果
                </div>
              )}
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>任务名称（可选）</label>
                <input type="text" placeholder="输入名称便于在导出任务列表中识别" style={{
                  width: '100%', padding: '7px 10px', fontSize: 14, borderRadius: 6,
                  border: '1px solid var(--divider)', outline: 'none', boxSizing: 'border-box' as any,
                }} value={exportTaskName} onChange={(e) => setExportTaskName(e.target.value)} />
              </div>
              <div style={{ marginBottom: 18, display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 14, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>导出条数：</span>
                <select id="exportLimitSelect" className="page-size-select" style={{ padding: '6px 8px' }}
                  value={exportLimit} onChange={(e) => setExportLimit(e.target.value)}>
                  <option value="1000">1000</option>
                  <option value="100">100</option>
                  <option value="500">500</option>
                  <option value="5000">5000</option>
                  <option value="10000">10000</option>
                  <option value="all">全部</option>
                </select>
                <input type="number" className="jump-input" style={{ width: 90 }} min={1} max={50000} placeholder="自定义"
                  value={exportLimit === 'all' ? '' : exportLimit}
                  onChange={(e) => setExportLimit(e.target.value)} />
              </div>
              <div className="modal-acts">
                <button type="button" className="btn-soft" onClick={() => setExportModalOpen(false)}>取消</button>
                <button type="button" className="btn-soft" style={{ background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)' }}
                  disabled={exportSubmitting} onClick={submitExport}>
                  {exportSubmitting ? '提交中…' : '开始导出'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Vuln Result Modal */}
        {vulnModal.open && (
          <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setVulnModal({ open: false, loading: false, data: null }) }}>
            <div className="modal-box result-modal-box">
              <div className="result-modal-head">
                <h3>漏洞验证结果</h3>
                <button type="button" className="result-modal-close" onClick={() => setVulnModal({ open: false, loading: false, data: null })}>×</button>
              </div>
              <div className="result-modal-body">
                {vulnModal.loading ? (
                  <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>加载中…</div>
                ) : vulnModal.data ? (
                  <pre className="result-modal-pre">
                    {[vulnModal.data.plugin_name, vulnModal.data.cve].filter(Boolean).join(' / ')}
                    {'\n\n'}
                    {vulnModal.data.result || '暂无结果内容'}
                  </pre>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>加载失败</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Help Modal */}
        <Modal
          title="资产检索说明"
          open={helpOpen}
          onCancel={() => setHelpOpen(false)}
          footer={<Button onClick={() => setHelpOpen(false)}>知道了</Button>}
          width={720}
          style={{ top: 40 }}
        >
          <div style={{ maxHeight: '70vh', overflow: 'auto', fontSize: 14, lineHeight: 1.8, color: 'var(--text-secondary)' }}>
            <HelpContent />
          </div>
        </Modal>

        {/* Toast */}
        {toastMsg && <div className="toast">{toastMsg}</div>}

        {/* Spin animation */}
        <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      </div>
    </>
  )
}

function HelpContent() {
  return (
    <>
      <h3 style={{ marginTop: 0, color: 'var(--text)' }}>一、检索字段</h3>
      <p>每个字段用 <code>字段:"值"</code> 格式搜索，多个条件用 <code>&&</code>（且）、<code>||</code>（或）组合。</p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--divider)', textAlign: 'left' }}>
              <th style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>字段</th>
              <th style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>含义</th>
              <th style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>示例</th>
            </tr>
          </thead>
          <tbody style={{ fontSize: 13 }}>
            <tr><td style={td}><code>ip</code></td><td style={td}>IP 地址</td><td style={td}><code>ip:"1.2.3.4"</code></td></tr>
            <tr><td style={td}><code>host</code></td><td style={td}>主机名/域名</td><td style={td}><code>host:"example.com"</code></td></tr>
            <tr><td style={td}><code>port</code></td><td style={td}>端口号</td><td style={td}><code>port:"443"</code></td></tr>
            <tr><td style={td}><code>protocol</code></td><td style={td}>协议</td><td style={td}><code>protocol:"http"</code></td></tr>
            <tr><td style={td}><code>title</code></td><td style={td}>网站标题</td><td style={td}><code>title:"管理后台"</code></td></tr>
            <tr><td style={td}><code>body</code></td><td style={td}>响应正文（子串匹配）</td><td style={td}><code>body:"登录"</code></td></tr>
            <tr><td style={td}><code>html</code></td><td style={td}>HTML 源码（子串匹配）</td><td style={td}><code>html:"&lt;form"</code></td></tr>
            <tr><td style={td}><code>header</code></td><td style={td}>响应头（子串匹配）</td><td style={td}><code>header:"Server: nginx"</code></td></tr>
            <tr><td style={td}><code>product</code></td><td style={td}>产品/中间件</td><td style={td}><code>product:"nginx"</code></td></tr>
            <tr><td style={td}><code>vuln</code></td><td style={td}>漏洞名称</td><td style={td}><code>vuln:"SQL注入"</code></td></tr>
            <tr><td style={td}><code>cve</code></td><td style={td}>CVE 编号</td><td style={td}><code>cve:"CVE-2024"</code></td></tr>
            <tr><td style={td}><code>favicon</code></td><td style={td}>favicon 图标 hash</td><td style={td}><code>favicon:"abc123def"</code></td></tr>
            <tr><td style={td}><code>cert</code></td><td style={td}>证书主体（CN）</td><td style={td}><code>cert:"*.example.com"</code></td></tr>
            <tr><td style={td}><code>cert_org</code></td><td style={td}>证书组织（O）</td><td style={td}><code>cert_org:"Let's Encrypt"</code></td></tr>
            <tr><td style={td}><code>cert_serial</code></td><td style={td}>证书序列号</td><td style={td}><code>cert_serial:"00abc123"</code></td></tr>
            <tr><td style={td}><code>country</code></td><td style={td}>国家</td><td style={td}><code>country:"中国"</code></td></tr>
            <tr><td style={td}><code>province</code></td><td style={td}>省份</td><td style={td}><code>province:"北京"</code></td></tr>
            <tr><td style={td}><code>city</code></td><td style={td}>城市</td><td style={td}><code>city:"北京"</code></td></tr>
            <tr><td style={td}><code>isp</code></td><td style={td}>运营商</td><td style={td}><code>isp:"电信"</code></td></tr>
            <tr><td style={td}><code>ipc</code></td><td style={td}>IP 段</td><td style={td}><code>ipc:"1.2.0.0/16"</code></td></tr>
            <tr><td style={td}><code>status_code</code></td><td style={td}>HTTP 状态码</td><td style={td}><code>status_code:"200"</code></td></tr>
            <tr><td style={td}><code>uri_path</code></td><td style={td}>URI 路径</td><td style={td}><code>uri_path:"/api"</code></td></tr>
            <tr><td style={td}><code>copyright</code></td><td style={td}>版权信息</td><td style={td}><code>copyright:"2024"</code></td></tr>
            <tr><td style={td}><code>icp</code></td><td style={td}>ICP 备案号</td><td style={td}><code>icp:"京ICP备"</code></td></tr>
          </tbody>
        </table>
      </div>

      <h3 style={{ color: 'var(--text)' }}>二、检索语法</h3>
      <ul style={{ paddingLeft: 20 }}>
        <li><b>AND</b>：<code>ip:"1.2.3.4" && port:"80"</code> — 同时满足两个条件。</li>
        <li><b>OR</b>：<code>port:"80" || port:"443"</code> — 满足任一条件。</li>
        <li><b>深度检索</b>：<code>html:="keyword"</code> — 用 <code>:=</code> 代替 <code>:</code>，走更准确的全文搜索。</li>
        <li><b>通配符</b>：<code>host:"*.example.com"</code> — 用 <code>*</code> 匹配任意字符（host/ip/uri_path 三个字段支持）。</li>
        <li><b>查不为空</b>：<code>vuln:"*"</code> — 查出所有有漏洞的资产（任意字段都可用）。</li>
        <li><b>查为空</b>：<code>vuln:"(空)"</code> — 查出该字段没有值的资产（等价于不含该字段）。</li>
        <li><b>不包含</b>：<code>!product:"nginx"</code> — 在产品中不包含 nginx 的资产。</li>
      </ul>

      <h3 style={{ color: 'var(--text)' }}>三、左侧聚类统计</h3>
      <ul style={{ paddingLeft: 20 }}>
        <li>每个检索列左边会显示该字段下所有值的数量分布（协议、端口、产品、地区等）。</li>
        <li>点击某个聚类值可以直接加到搜索条件中。</li>
        <li>点击 <b>"(空)"</b> 项可以搜出该字段为空的资产。</li>
        <li>热门 favicon 区域出现在统计面板最上方，点击可追加到搜索条件。</li>
        <li>左侧面板顶部有"面板"按钮，页面窄时可以展开/收起侧边栏。</li>
      </ul>

      <h3 style={{ color: 'var(--text)' }}>四、导出</h3>
      <ul style={{ paddingLeft: 20 }}>
        <li><b>导出</b>：点击顶部工具栏的"导出"按钮，选择导出字段和条数，生成的导出文件出现在"导出任务"页面。</li>
        <li><b>快导</b>：顶部"快导"按钮直接下载当前检索结果（不超过默认上限）。</li>
      </ul>

      <h3 style={{ color: 'var(--text)' }}>五、其他功能</h3>
      <ul style={{ paddingLeft: 20 }}>
        <li><b>全部区域</b>：顶部下拉可以选择具体的扫描区域，或选"所有内网"排除公网资产。</li>
        <li><b>卡片展开</b>：每张结果卡片可以点"展开"查看详情——包括漏洞列表、端口概览、同 IP 其他资产。</li>
        <li><b>展开全部</b>：顶部"展开全部"按钮可以一次性展开当前页所有卡片。</li>
        <li><b>每页条数</b>：底部可以切换每页 13 / 25 / 50 / 100 条。</li>
        <li><b>页面跳转</b>：底部输入页码可以直接跳转到指定页。</li>
        <li><b>URL 参数</b>：当前搜索条件、页码、每页条数、区域选择都会同步到浏览器地址栏，复制 URL 即可分享当前视图。</li>
      </ul>
    </>
  )
}

const td: React.CSSProperties = { padding: '5px 8px', borderBottom: '1px solid var(--divider)', verticalAlign: 'top' }
