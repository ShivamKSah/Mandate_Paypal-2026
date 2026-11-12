import React, { useMemo, useRef, useState, useEffect } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  type ColDef,
  type ICellRendererParams,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { Download, Search, ShieldCheck, Zap } from "lucide-react";
import { type Payment, type Proposal } from "./api";
import { date, money } from "./domain";

ModuleRegistry.registerModules([AllCommunityModule]);

export function AgGridPayments({
  payments,
  proposals,
}: {
  payments: Payment[];
  proposals: Proposal[];
}) {
  const gridRef = useRef<AgGridReact<Payment>>(null);
  const [quickFilter, setQuickFilter] = useState("");
  const [isDark, setIsDark] = useState(() => {
    if (typeof document !== "undefined") {
      return document.documentElement.getAttribute("data-theme") === "dark";
    }
    return false;
  });

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.getAttribute("data-theme") === "dark");
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  const byProposal = useMemo(
    () => new Map(proposals.map((p) => [p.id, p])),
    [proposals],
  );

  const columnDefs = useMemo<ColDef<Payment>[]>(
    () => [
      {
        field: "status",
        headerName: "PayPal Status",
        flex: 1.1,
        minWidth: 140,
        sortable: true,
        filter: true,
        cellRenderer: (params: ICellRendererParams<Payment>) => {
          if (!params.value) return "—";
          const val = String(params.value);
          const isCaptured = val === "CAPTURED";
          const isRefunded = val === "REFUNDED";
          return (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                fontSize: "11px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "999px",
                background: isCaptured
                  ? "var(--green-soft, rgba(16,185,129,0.12))"
                  : isRefunded
                    ? "var(--amber-soft, rgba(245,158,11,0.12))"
                    : "var(--surface-raised, rgba(0,0,0,0.06))",
                color: isCaptured
                  ? "var(--green, #10b981)"
                  : isRefunded
                    ? "var(--amber, #f59e0b)"
                    : "var(--muted, #64748b)",
                textTransform: "uppercase",
              }}
            >
              {val.replaceAll("_", " ")}
            </span>
          );
        },
      },
      {
        field: "provider_order_id",
        headerName: "PayPal Order ID",
        flex: 1.3,
        minWidth: 150,
        sortable: true,
        filter: true,
        cellRenderer: (params: ICellRendererParams<Payment>) => {
          if (!params.value) return <span style={{ color: "var(--muted)" }}>Pre-order reservation</span>;
          return (
            <code
              style={{
                fontFamily: "var(--mono, monospace)",
                fontSize: "11px",
                background: "var(--surface-raised, rgba(0,0,0,0.04))",
                padding: "2px 6px",
                borderRadius: "4px",
              }}
            >
              {params.value}
            </code>
          );
        },
      },
      {
        field: "provider_capture_id",
        headerName: "Capture ID",
        flex: 1.2,
        minWidth: 140,
        sortable: true,
        filter: true,
        cellRenderer: (params: ICellRendererParams<Payment>) => {
          if (!params.value) return <span style={{ color: "var(--muted)" }}>—</span>;
          return (
            <code
              style={{
                fontFamily: "var(--mono, monospace)",
                fontSize: "11px",
                color: "var(--green, #10b981)",
              }}
            >
              {params.value}
            </code>
          );
        },
      },
      {
        headerName: "Proposal / Cart",
        flex: 1.5,
        minWidth: 180,
        valueGetter: (params) => {
          const p = byProposal.get(params.data?.proposal_id ?? "");
          if (!p) return params.data?.proposal_id ?? "—";
          return p.items.map((i) => i.name ?? i.product_id).join(", ");
        },
      },
      {
        field: "amount_cents",
        headerName: "Authorized",
        flex: 1,
        minWidth: 110,
        sortable: true,
        valueFormatter: (params) => (params.value ? money(params.value) : "—"),
      },
      {
        field: "refunded_cents",
        headerName: "Refunded",
        flex: 1,
        minWidth: 110,
        sortable: true,
        valueFormatter: (params) => (params.value ? money(params.value) : "—"),
      },
      {
        headerName: "Execution State",
        flex: 1.2,
        minWidth: 140,
        sortable: true,
        cellRenderer: (params: ICellRendererParams<Payment>) => {
          const hasCapture = Boolean(params.data?.provider_capture_id);
          return (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                fontSize: "11px",
                fontWeight: 600,
                color: hasCapture ? "var(--green, #10b981)" : "var(--muted, #64748b)",
              }}
            >
              {hasCapture ? <Zap size={13} /> : <ShieldCheck size={13} />}
              {hasCapture ? "Settled on PayPal" : "Reserved / Pending"}
            </span>
          );
        },
      },
      {
        field: "created_at",
        headerName: "Timestamp",
        flex: 1.2,
        minWidth: 130,
        sortable: true,
        valueFormatter: (params) => (params.value ? date(params.value) : "—"),
      },
    ],
    [byProposal],
  );

  const handleExportCsv = () => {
    gridRef.current?.api.exportDataAsCsv({
      fileName: `mandate-paypal-payments-${new Date().toISOString().slice(0, 10)}.csv`,
    });
  };

  const onFilterChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuickFilter(val);
    gridRef.current?.api.setGridOption("quickFilterText", val);
  };

  return (
    <div className="ag-grid-container" style={{ width: "100%", marginTop: "12px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "12px",
          marginBottom: "10px",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            position: "relative",
            display: "inline-flex",
            alignItems: "center",
            minWidth: "260px",
          }}
        >
          <Search
            size={14}
            style={{
              position: "absolute",
              left: "10px",
              color: "var(--muted)",
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            placeholder="Search payments, order IDs, statuses..."
            value={quickFilter}
            onChange={onFilterChange}
            style={{
              width: "100%",
              padding: "7px 12px 7px 32px",
              fontSize: "12px",
              borderRadius: "8px",
              border: "1px solid var(--line)",
              background: "var(--paper)",
              color: "var(--ink)",
            }}
          />
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            type="button"
            className="button-outline"
            onClick={handleExportCsv}
            style={{ fontSize: "12px", minHeight: "32px", padding: "4px 10px" }}
          >
            <Download size={13} /> Export CSV
          </button>
        </div>
      </div>
      <div
        className={isDark ? "ag-theme-quartz-dark" : "ag-theme-quartz"}
        style={{
          height: "440px",
          width: "100%",
          borderRadius: "12px",
          overflow: "hidden",
          border: "1px solid var(--line)",
        }}
      >
        <AgGridReact<Payment>
          ref={gridRef}
          rowData={payments}
          columnDefs={columnDefs}
          defaultColDef={{
            resizable: true,
          }}
          pagination={true}
          paginationPageSize={10}
          paginationPageSizeSelector={[10, 25, 50]}
        />
      </div>
    </div>
  );
}
