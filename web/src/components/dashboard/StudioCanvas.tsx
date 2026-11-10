"use client";

import { useMemo } from "react";
import { AgStudio, AgStudioProvider, createWidgets, type AgWidgetDefinition } from "ag-studio-react";
import { singleColumnLayout, studioTheme, type AgDataSourcesDefinition, type AgReportState, type AgDefaultRegistry, type AgWidgetData, type AgWidgetDataFormat, type AgWidgetParams } from "ag-studio";
import { MoneyText, Notice } from "@/components/ui";
import type { DashboardCase, DashboardOut } from "@/lib/dashboard-types";
import { paymentStateLabel } from "@/lib/dashboard-types";
import { CASE_STATUS_LABEL } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import styles from "./studio.module.css";

interface ExactTotalsState extends AgWidgetData<Record<string,never>,AgWidgetDataFormat<Record<string,never>>> { type:"exactTotals" }
interface FamilyRegistry extends Omit<AgDefaultRegistry,"widgets"> { widgets:readonly (AgDefaultRegistry["widgets"][number] | AgWidgetDefinition<"exactTotals",ExactTotalsState>)[] }
type FamilyContext = {totals:DashboardOut["totals"];needsReconciliation:boolean};

function ExactTotalsWidget({context}:AgWidgetParams<ExactTotalsState,unknown,FamilyContext>) {
  return <div className={styles.exactTotals} tabIndex={0} role="region" aria-label="Hospital bill totals by currency"><h2>Hospital bill totals by currency</h2><p>Totals include all cases before insurance allocation. These are not the family payment amounts.</p>{context.needsReconciliation ? <Notice tone="warning" title="Amounts need checking"><p>These totals include cases with unresolved accounting checks. Review their issues in Cases before approving any amount.</p></Notice> : null}{context.totals.map(total=><div className={styles.exactCurrency} key={total.currency}><h3>{total.currency}</h3><dl><div><dt>Unpaid bill balance</dt><dd><MoneyText value={total.payable_now} currency={total.currency}/></dd></div><div><dt>Queried</dt><dd><MoneyText value={total.queried} currency={total.currency}/></dd></div><div><dt>Already paid</dt><dd><MoneyText value={total.already_paid} currency={total.currency}/></dd></div></dl></div>)}</div>;
}

const widgets = createWidgets<FamilyRegistry>({additionalTypes:[{id:"exactTotals",label:"Exact family balances",comp:ExactTotalsWidget,dataMapping:{},form:params=>params.createDefaults({dataMappingItems:[]}),defaultSize:{width:700,height:280},minSize:{width:250,height:420},toolbar:[]}],menu:[{label:"Family evidence",widgetIds:["exactTotals","grid"]}]});

const theme = studioTheme.withParams({fontFamily:"var(--cd-font-sans)",fontSize:14,textColor:"var(--cd-color-ink)",backgroundColor:"var(--cd-color-sheet)",accentColor:"var(--cd-color-action)",borderColor:"var(--cd-color-rule)",studioMinWidth:0,studioMinHeight:400});
const fields = [ ["reference","Case"], ["provider","Provider"], ["status","Stage"], ["payable","Unpaid bill balance"], ["queried","Queried"], ["paid","Already paid"], ["questions","Open questions"], ["replies","Replies to review"], ["payment","Payment state"] ];
const initialState:AgReportState<FamilyRegistry> = {pages:[{id:"family",widgets:{cases:{type:"grid",dataMapping:{cols:fields.map(([id])=>({id:`cases.${id}`}))},format:{title:{enabled:true,text:"Family case record"},style:{columnWidth:180,columnAutoSize:true,headerRow:{wrapText:false}}}},totals:{type:"exactTotals",dataMapping:{}}},widgetLayout:{totals:{xTrack:0,yTrack:0,xSpan:24,ySpan:27},cases:{xTrack:0,yTrack:27,xSpan:24,ySpan:24}},layout:{minWidth:250,columns:24,rowHeight:16}}],selectedPageId:"family",panels:{filters:{collapsed:true}}};

export default function StudioCanvas({cases,totals,licenseKey,needsReconciliation}: {cases:DashboardCase[];totals:DashboardOut["totals"];licenseKey?:string;needsReconciliation:boolean}) {
  const data = useMemo<AgDataSourcesDefinition<FamilyRegistry>>(()=>({sources:[{id:"cases",name:"Authorized family cases",transactions:"none",fields:fields.map(([id,name])=>({id,name,format:"textFormat",editable:false})),data:cases.map(item=>({reference:item.case_reference,provider:item.provider_name,status:CASE_STATUS_LABEL[item.status],payable:formatMoney(item.buckets.payable_now,item.currency),queried:formatMoney(item.buckets.queried,item.currency),paid:formatMoney(item.buckets.already_paid,item.currency),questions:String(item.open_questions),replies:String(item.pending_responses),payment:paymentStateLabel(item.payment_state)}))},{id:"totals",name:"Authoritative currency totals",transactions:"none",fields:[{id:"currency",name:"Currency",format:"textFormat"},{id:"payable",name:"Unpaid bill balance",format:"textFormat"},{id:"queried",name:"Queried",format:"textFormat"},{id:"paid",name:"Already paid",format:"textFormat"}],data:totals.map(total=>({currency:total.currency,payable:formatMoney(total.payable_now,total.currency),queried:formatMoney(total.queried,total.currency),paid:formatMoney(total.already_paid,total.currency)}))}]}),[cases,totals]);
  const context = useMemo<FamilyContext>(()=>({totals,needsReconciliation}),[totals,needsReconciliation]);
  return <AgStudioProvider licenseKey={licenseKey}><AgStudio<FamilyRegistry> style={{height:"100%",width:"100%"}} theme={theme} context={context} widgets={widgets} loadThemeGoogleFonts={false} mode="view" data={data} initialState={initialState} panels={{view:{left:[],right:[]},edit:{left:[],right:[]}}} responsiveLayoutBreakpoints={[{maxWidth:700,layout:singleColumnLayout}]} /></AgStudioProvider>;
}
