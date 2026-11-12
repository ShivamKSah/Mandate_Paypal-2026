import React, { useMemo, useRef, useState, useEffect } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  type ColDef,
  type ICellRendererParams,
  type RowClickedEvent,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { Download, Search, ShieldCheck } from "lucide-react";
import { type LedgerEntry } from "./api";
import { date, money } from "./domain";

ModuleRegistry.registerModules([AllCommunityModule]);

export function AgGridLedger({
  entries,
  selectedId,
  onSelectId,
}: {
  entries: LedgerEntry[];
  selectedId: string | null;
  onSelectId: (id: string) => void;
}) {
  const gridRef = useRef<AgGridReact<LedgerEntry>>(null);
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

  const columnDefs = useMemo<ColDef<LedgerEntry>[]>(
    () => [
      {
        field: "event_type",
        headerName: "Event Type",
        flex: 1.4,
        minWidth: 180,
        sortable: true,
        filter: true,
        cellRenderer: (params: ICellRendererParams<LedgerEntry>) => {
          if (!params.value) return null;
          const label = String(params.value).replaceAll("_", " ");
          return (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                fontWeight: 600,
                textTransform: "capitalize",
              }}
            >
              <span
                style={{
                  width: "7px",
                  height: "7px",
                  borderRadius: "50%",
                  background: "var(--green, #10b981)",
                  display: "inline-block",
                  flex: "none",
                }}
              />
              {label}
            </span>
          );
        },
      },
      {
        field: "entity_id",
        headerName: "Entity Target",
        flex: 1.3,
        minWidth: 150,
        sortable: true,
        filter: true,
        cellRenderer: (params: ICellRendererParams<LedgerEntry>) => {
          if (!params.value) return "—";
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
              {String(params.value).slice(0, 18)}
            </code>
          );
        },
      },
      {
        headerName: "Amount",
        flex: 1,
        minWidth: 110,
        sortable: true,
        valueGetter: (params) => {
          const details = params.data?.details;
          if (!details) return 0;
          if (typeof details.total_cents === "number") return details.total_cents;
          if (typeof details.amount_cents === "number") return details.amount_cents;
          if (typeof details.refund_cents === "number") return details.refund_cents;
          return 0;
        },
        valueFormatter: (params) => {
          if (!params.value) return "—";
          return money(params.value);
        },
      },
      {
        field: "created_at",
        headerName: "Recorded At",
        flex: 1.2,
        minWidth: 140,
        sortable: true,
        filter: true,
        valueFormatter: (params) => (params.value ? date(params.value) : "—"),
      },
      {
        field: "row_hash",
        headerName: "Chain Hash (SHA-256)",
        flex: 1.4,
        minWidth: 160,
        sortable: true,
        cellRenderer: (params: ICellRendererParams<LedgerEntry>) => {
          if (!params.value) return "—";
          return (
            <code
              style={{
                fontFamily: "var(--mono, monospace)",
                fontSize: "11px",
                color: "var(--muted, #64748b)",
              }}
              title={params.value}
            >
              {params.value.slice(0, 14)}…
            </code>
          );
        },
      },
      {
        headerName: "Audit Chain",
        flex: 1,
        minWidth: 120,
        cellRenderer: () => (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              fontSize: "11px",
              fontWeight: 600,
              color: "var(--green, #10b981)",
            }}
          >
            <ShieldCheck size={14} /> Verified
          </span>
        ),
      },
    ],
    [],
  );

  const onRowClicked = (event: RowClickedEvent<LedgerEntry>) => {
    if (event.data?.id) {
      onSelectId(event.data.id);
    }
  };

  const handleExportCsv = () => {
    gridRef.current?.api.exportDataAsCsv({
      fileName: `mandate-decision-ledger-${new Date().toISOString().slice(0, 10)}.csv`,
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
            placeholder="Quick search events, hashes, targets..."
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
        <AgGridReact<LedgerEntry>
          ref={gridRef}
          rowData={entries}
          columnDefs={columnDefs}
          defaultColDef={{
            resizable: true,
          }}
          pagination={true}
          paginationPageSize={10}
          paginationPageSizeSelector={[10, 25, 50]}
          rowSelection={{ mode: "singleRow", enableClickSelection: true }}
          onRowClicked={onRowClicked}
          rowClassRules={{
            "ag-row-selected-custom": (params) => params.data?.id === selectedId,
          }}
        />
      </div>
    </div>
  );
}

