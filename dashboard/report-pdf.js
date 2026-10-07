const PDF_RENDER_SCALE = 1.35;
const PDF_JPEG_QUALITY = 0.7;
let pdfExportInProgress = false;

function waitForReportImages(root, timeoutMs = 5000) {
  const images = Array.from(root.querySelectorAll("img"));
  if (!images.length) return Promise.resolve();
  return Promise.all(
    images.map(
      (image) =>
        new Promise((resolve) => {
          if (image.complete) {
            resolve();
            return;
          }
          const done = () => resolve();
          image.addEventListener("load", done, { once: true });
          image.addEventListener("error", done, { once: true });
          setTimeout(done, timeoutMs);
        }),
    ),
  );
}

function collectPdfKeepTogetherRanges(root) {
  const rootRect = root.getBoundingClientRect();
  if (!rootRect.height) return [];

  return Array.from(
    root.querySelectorAll(
      "[data-pdf-keep-together], #reportEvidenceGallery figure, table tr, canvas",
    ),
  )
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: Math.max(0, rect.top - rootRect.top),
        bottom: Math.min(rootRect.height, rect.bottom - rootRect.top),
      };
    })
    .filter((range) => range.bottom - range.top > 1);
}

function choosePdfSliceEnd(
  sourceStart,
  desiredEnd,
  pagePixelHeight,
  keepTogetherRanges,
) {
  const crossingRanges = keepTogetherRanges.filter((range) => {
    const height = range.bottom - range.top;
    return (
      height <= pagePixelHeight &&
      range.top > sourceStart + 1 &&
      range.top < desiredEnd &&
      range.bottom > desiredEnd
    );
  });
  if (!crossingRanges.length) return desiredEnd;

  const safeEnd = Math.min(...crossingRanges.map((range) => range.top));
  return safeEnd > sourceStart + 1 ? safeEnd : desiredEnd;
}

function generatePDF(labId) {
  const source = document.getElementById("reportContent");
  if (!source || source.classList.contains("hidden")) {
    alert("ไม่พบเนื้อหารายงาน");
    return;
  }
  if (typeof html2canvas === "undefined" || !window.jspdf) {
    alert("ไม่สามารถสร้าง PDF ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
    return;
  }
  if (pdfExportInProgress) return;
  pdfExportInProgress = true;

  // Capture an isolated copy so export never resizes the page the user is reading.
  const exportHost = document.createElement("div");
  exportHost.style.cssText = "position:fixed;left:0;top:0;width:1280px;z-index:-1000;pointer-events:none;";
  exportHost.setAttribute("aria-hidden", "true");
  const reportContent = source.cloneNode(true);
  reportContent.id = "reportPdfContent";
  reportContent.classList.add("pdf-report");
  reportContent.style.width = "1280px";
  reportContent.querySelector("#reportMethodologySection").open = true;
  for (const wrapper of reportContent.querySelectorAll("[id$='TableWrapper']")) {
    wrapper.style.overflow = "visible";
  }
  reportContent.querySelector("#reportBehaviorEventsSection").style.display = "none";
  exportHost.append(reportContent);
  document.body.append(exportHost);

  return Promise.all([waitForReportImages(reportContent), document.fonts?.ready])
    .then(() => {
      const contentHeight = reportContent.getBoundingClientRect().height;
      const keepTogetherRanges = collectPdfKeepTogetherRanges(reportContent);
      return html2canvas(reportContent, {
        scale: PDF_RENDER_SCALE,
        useCORS: true,
        backgroundColor: "#ffffff",
        scrollX: 0,
        scrollY: 0,
        windowWidth: 1440,
      })
        .then((canvas) => ({
          canvas,
          contentHeight,
          keepTogetherRanges,
        }));
    })
    .then(({ canvas, contentHeight, keepTogetherRanges }) => {
      exportHost.remove();

      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const imageWidth = pageWidth - margin * 2;
      const pageContentHeight = pageHeight - margin * 2;
      const pagePixelHeight =
        (pageContentHeight / imageWidth) * canvas.width;
      const canvasScaleY = canvas.height / Math.max(1, contentHeight);
      const scaledRanges = keepTogetherRanges.map((range) => ({
        top: range.top * canvasScaleY,
        bottom: range.bottom * canvasScaleY,
      }));

      let sourceY = 0;
      let pageIndex = 0;
      while (sourceY < canvas.height) {
        const desiredEnd = Math.min(
          canvas.height,
          sourceY + pagePixelHeight,
        );
        const safeEnd = choosePdfSliceEnd(
          sourceY,
          desiredEnd,
          pagePixelHeight,
          scaledRanges,
        );
        const sliceEnd = Math.max(
          sourceY + 1,
          Math.min(canvas.height, Math.floor(safeEnd)),
        );
        const slicePixelHeight = sliceEnd - sourceY;
        const sliceHeight =
          (slicePixelHeight * imageWidth) / canvas.width;
        const sliceCanvas = document.createElement("canvas");
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = slicePixelHeight;
        const context = sliceCanvas.getContext("2d");
        context.drawImage(
          canvas,
          0,
          sourceY,
          canvas.width,
          slicePixelHeight,
          0,
          0,
          sliceCanvas.width,
          sliceCanvas.height,
        );

        if (pageIndex > 0) pdf.addPage();
        pdf.addImage(
          sliceCanvas.toDataURL("image/jpeg", PDF_JPEG_QUALITY),
          "JPEG",
          margin,
          margin,
          imageWidth,
          sliceHeight,
          undefined,
          "FAST",
        );
        sourceY = sliceEnd;
        pageIndex += 1;
      }

      pdf.save(`ClassMood_Report_${labId}_${Date.now()}.pdf`);
    })
    .catch((error) => {
      console.error("Error generating PDF:", error);
      alert("ไม่สามารถสร้าง PDF ได้");
    })
    .finally(() => {
      exportHost.remove();
      pdfExportInProgress = false;
    });
}
