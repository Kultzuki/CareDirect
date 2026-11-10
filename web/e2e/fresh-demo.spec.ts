import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { API_URL, getDemoPayer } from "./helpers";

const output = path.resolve(__dirname, "../../output/playwright/prompt08");
const targets = [["desktop1440",1440,900],["desktop1280",1280,800],["tablet768",768,1024],["mobile390",390,844],["mobile360",360,800]] as const;

async function capture(page: Page, state: string) {
  fs.mkdirSync(output, {recursive:true});
  for (const [name,width,height] of targets) {
    await page.setViewportSize({width,height});
    await page.screenshot({path:path.join(output,`${state}-${name}.png`),fullPage:true});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`${state} fits ${width}`).toBe(true);
  }
  expect((await new AxeBuilder({page}).exclude("nextjs-portal").analyze()).violations).toEqual([]);
  await page.setViewportSize({width:1440,height:900});
}

for (const run of [1,2]) test(`complete fresh UI demo ${run} preserves evidence and history (mock payment HTTP)`, async ({page,request,context}) => {
  test.skip(process.env.CAREDIRECT_E2E_MOCK !== "1", "Isolated no-network payment harness required");
  test.setTimeout(300_000);
  fs.mkdirSync(output,{recursive:true});
  const errors: string[]=[];
  page.on("pageerror",error => errors.push(error.message));
  page.on("console",message => {if(message.type()==="error") errors.push(message.text());});
  const payer = await getDemoPayer(request);
  const headers={"X-Demo-User-Id":payer};
  const initialCases=await (await request.get(`${API_URL}/api/dashboard`,{headers})).json() as {cases:{id:string}[]};
  await page.goto("/cases");
  await expect(page.getByRole("heading",{name:"The family record"})).toBeVisible();
  if(run===1) await capture(page,"family-dashboard");
  const files: Record<string,string>={};
  for (const [label,name] of [["Bill PDF — USD250","usd_bill.pdf"],["Estimate PDF — USD250","usd_estimate.pdf"],["Prior receipt PDF — USD40","usd_receipt.pdf"]]) {
    const downloaded=page.waitForEvent("download");
    await page.getByRole("link",{name:label,exact:true}).click();
    const download=await downloaded;
    files[name]=path.join(output,`run${run}-${name}`);
    await download.saveAs(files[name]);
    expect(fs.statSync(files[name]).size).toBeGreaterThan(500);
  }
  const create=page.getByRole("button",{name:"Create fresh synthetic case",exact:true});
  await create.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({hasText:"Fresh case created"})).toBeVisible();
  const open=page.getByRole("link",{name:/Open DEMO-E-/});
  const href=await open.getAttribute("href");
  const caseId=href!.split("/")[2];
  await page.reload(); // recovering after navigation must retain the same run
  await page.getByRole("button",{name:"Create fresh synthetic case",exact:true}).click();
  await expect(page.getByRole("link",{name:/Open DEMO-E-/})).toHaveAttribute("href",href!);
  await page.getByRole("link",{name:/Open DEMO-E-/}).click();
  await page.getByRole("checkbox",{name:"Estimate",exact:true}).check();
  await page.getByRole("button",{name:"Create upload link",exact:true}).click();
  await page.getByRole("link",{name:"Open upload page",exact:true}).click();
  for (const [kind,name] of [["Bill","usd_bill.pdf"],["Estimate","usd_estimate.pdf"],["Receipt","usd_receipt.pdf"]]) {
    await page.getByLabel("Document type").selectOption({label:kind});
    await page.getByLabel("File",{exact:true}).setInputFiles(files[name]);
    await page.getByRole("button",{name:"Upload",exact:true}).click();
    await expect(page.getByRole("status").filter({hasText:"Uploaded"})).toContainText(`${kind}:`);
  }
  for (const kind of ["Bill","Estimate","Receipt"]) {
    await page.goto(`/cases/${caseId}/review`);
    const row=page.getByTestId("document-list").getByRole("listitem").filter({has:page.getByRole("heading",{name:kind,exact:true})});
    await row.getByRole("button",{name:/^Extract/}).click();
    await expect(page.getByTestId("mock-label")).toContainText("replayed synthetic output");
    if(kind==="Bill") {
      await expect(page.getByRole("button",{name:"Add to case",exact:true})).toBeDisabled();
      await page.getByLabel("Corrected value for Provider identifier",{exact:true}).fill("SYN-REG-0001");
      await page.getByLabel("Reason for changes",{exact:true}).fill("Human checked registration against readable source; preserve original model reading.");
      await page.getByRole("button",{name:"Save review",exact:true}).click();
      await expect(page.getByTestId("field-provider_identifier")).toContainText("Corrected");
      if(run===1) await capture(page,"review-source");
      await page.reload();
    }
    if(kind!=="Estimate") {
      await page.getByRole("button",{name:"Add to case",exact:true}).click();
      await expect(page.getByTestId("promoted-notice")).toBeVisible();
    }
  }
  await page.goto(`/cases/${caseId}`);
  for(const number of [1,2,3]) await page.getByRole("button",{name:`Accept line ${number} after review`,exact:true}).click();
  await page.getByRole("button",{name:"Review prior payment evidence",exact:true}).click();
  await expect(page.getByText("Evidence matched",{exact:false}).first()).toBeVisible();
  await page.getByRole("button",{name:"Refresh bill checks",exact:true}).click();
  const card=page.locator('[data-testid^="question-"]').filter({has:page.getByRole("heading",{name:"Possible duplicate",exact:true})}).first();
  await expect(card).toBeVisible();
  await card.getByLabel("Charge to question").selectOption({index:1});
  await card.getByLabel("Your question to the provider").fill("Please clarify the repeated laboratory panel on the readable synthetic bill.");
  await card.getByRole("button",{name:"Preview provider question",exact:true}).click();
  await expect(card.getByRole("heading",{name:"What the provider will see"})).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(card.getByLabel("Your question to the provider")).toBeFocused();
  await card.getByRole("button",{name:"Preview provider question",exact:true}).click();
  await card.getByRole("button",{name:"Hold charge and create provider link",exact:true}).click();
  const privatePath=await card.getByLabel("Private provider link").inputValue();
  const provider=await context.newPage();
  await provider.goto(privatePath);
  await provider.getByRole("radio",{name:"Credit the charge",exact:true}).check();
  await provider.getByLabel("Reason and supporting explanation").fill("Synthetic billing review confirms the duplicate row and proposes its full USD20 credit.");
  await provider.getByLabel("Your name or billing-team reference").fill("Synthetic billing desk");
  await provider.getByRole("button",{name:"Review response",exact:true}).click();
  await provider.getByRole("button",{name:"Record response for payer review",exact:true}).click();
  await expect(provider.getByRole("status").filter({hasText:"Response recorded"})).toBeVisible();
  await provider.reload();
  await expect(provider.getByText("This link cannot submit another response.",{exact:false})).toBeVisible();
  await provider.close();
  await page.reload();
  await card.getByRole("button",{name:"Review financial effect",exact:true}).click();
  await card.getByLabel("Reason for your decision").fill("I reviewed the original rows and accept the full USD20 credit.");
  await card.getByRole("checkbox").check();
  await card.getByRole("button",{name:"Accept resolution: $0.00",exact:true}).click();
  await expect(card.getByText("Resolution accepted",{exact:true})).toBeVisible();
  await page.reload();
  await expect(card.getByRole("button",{name:"Accept resolution: $0.00",exact:true})).toHaveCount(0);
  await page.getByRole("link",{name:"Payments",exact:true}).click();
  await page.getByRole("button",{name:"Check Sandbox account evidence",exact:true}).click();
  await page.getByRole("button",{name:"Review approval for $190.00",exact:true}).click();
  await page.getByLabel("Payment purpose",{exact:true}).fill("Synthetic USD190 exact reviewed remaining balance.");
  await page.getByRole("checkbox").check();
  await page.getByRole("button",{name:"Approve $190.00 collection",exact:true}).click();
  await expect(page.getByText("Current approval recorded",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Create approved Sandbox invoice",exact:true}).click();
  await expect(page.getByText("Awaiting Sandbox buyer",{exact:true})).toBeVisible();
  const workspace=await (await request.get(`${API_URL}/api/cases/${caseId}/payments`,{headers})).json() as {invoice:{paypal_invoice_id:string}};
  // The only test-side mutation: deterministic HTTP simulates a completed capture.
  // No real buyer login/checkout or PayPal network call occurs.
  expect((await request.post(`${API_URL}/__test__/invoices/${workspace.invoice.paypal_invoice_id}/complete`)).ok()).toBe(true);
  await page.getByRole("button",{name:"Verify current PayPal state",exact:true}).click();
  await expect(page.getByText("Payment verified by PayPal",{exact:true})).toBeVisible();
  await page.reload();
  await page.getByRole("button",{name:"Verify current PayPal state",exact:true}).click();
  await page.goto(`/cases/${caseId}/evidence`);
  await expect(page.getByRole("heading",{name:"Activity & evidence",exact:true})).toBeVisible();
  if(run===1) await capture(page,"evidence-record");
  for(const [label,format] of [["Download readable HTML","html"],["Download structured JSON","json"]]) {
    const downloaded=page.waitForEvent("download");
    await page.getByRole("link",{name:label,exact:true}).click();
    const download=await downloaded;
    const dest=path.join(output,`run${run}-evidence.${format}`);
    await download.saveAs(dest);
    const text=fs.readFileSync(dest,"utf8");
    expect(text).not.toMatch(/storage_key|token_sha256|checkout_url|sandbox\.paypal\.com|\/provider\/respond\//);
    if(format==="json") {
      const evidence=JSON.parse(text);
      expect(evidence.buckets).toMatchObject({original_bill_total:"250.00",adjustments:"-20.00",net_bill_total:"230.00",already_paid:"230.00",payable_now:"0.00",queried:"0.00"});
      expect(evidence.revisions).toHaveLength(1);
      expect(evidence.payer_decisions).toHaveLength(1);
      expect(evidence.approvals[0].approved_amount).toBe("190.00");
      expect(evidence.ledger.filter((entry:{entry_type:string})=>entry.entry_type==="PAYPAL_PAYMENT")).toHaveLength(1);
    }
  }
  const after=await (await request.get(`${API_URL}/api/dashboard`,{headers})).json() as {cases:{id:string}[]};
  expect(after.cases).toHaveLength(initialCases.cases.length+1);
  for(const previous of initialCases.cases) expect(after.cases.some(item=>item.id===previous.id)).toBe(true);
  expect(errors).toEqual([]);
});

test("family Studio renders authorized records at five viewports",async({page})=>{
  test.skip(process.env.STUDIO_LOCAL_EVALUATION!=="true","Explicit local Studio evaluation only");
  test.setTimeout(120_000);
  await page.goto("/cases/studio");
  await expect(page.getByRole("heading",{name:/Family Studio/})).toBeVisible();
  await expect(page.locator(".ag-root-wrapper").first()).toBeVisible();
  await capture(page,"family-studio");
});
