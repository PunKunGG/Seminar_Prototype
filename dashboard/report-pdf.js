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
  const reportContent = document.querySelector("#reportModal .bg-white");
  if (!reportContent) {
    alert("ไม่พบเนื้อหารายงาน");
    return;
  }
  if (typeof html2canvas === "undefined" || !window.jspdf) {
    alert("ไม่สามารถสร้าง PDF ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
    return;
  }

  const dlSection = document.getElementById("reportDownloadActions");
  const closeButton = document.getElementById("reportCloseButton");
  const timelineWrapper = document.getElementById("reportTimelineTableWrapper");
  const trackingWrapper = document.getElementById("reportTrackingTableWrapper");
  const savedStyles = {
    maxHeight: reportContent.style.maxHeight,
    overflow: reportContent.style.overflow,
    width: reportContent.style.width,
    maxWidth: reportContent.style.maxWidth,
    actionsDisplay: dlSection?.style.display || "",
    closeDisplay: closeButton?.style.display || "",
    timelineOverflow: timelineWrapper?.style.overflow || "",
    trackingOverflow: trackingWrapper?.style.overflow || "",
  };
  const restoreReportLayout = () => {
    reportContent.style.maxHeight = savedStyles.maxHeight;
    reportContent.style.overflow = savedStyles.overflow;
    reportContent.style.width = savedStyles.width;
    reportContent.style.maxWidth = savedStyles.maxWidth;
    if (dlSection) dlSection.style.display = savedStyles.actionsDisplay;
    if (closeButton) closeButton.style.display = savedStyles.closeDisplay;
    if (timelineWrapper) timelineWrapper.style.overflow = savedStyles.timelineOverflow;
    if (trackingWrapper) trackingWrapper.style.overflow = savedStyles.trackingOverflow;
  };

  reportContent.style.maxHeight = "none";
  reportContent.style.overflow = "visible";
  reportContent.style.width = "1200px";
  reportContent.style.maxWidth = "1200px";
  if (dlSection) dlSection.style.display = "none";
  if (closeButton) closeButton.style.display = "none";
  if (timelineWrapper) timelineWrapper.style.overflow = "visible";
  if (trackingWrapper) trackingWrapper.style.overflow = "visible";

  waitForReportImages(reportContent)
    .then(() => {
      const contentHeight = reportContent.getBoundingClientRect().height;
      const keepTogetherRanges = collectPdfKeepTogetherRanges(reportContent);
      return html2canvas(reportContent, { scale: 2, useCORS: true })
        .then((canvas) => ({
          canvas,
          contentHeight,
          keepTogetherRanges,
        }));
    })
    .then(({ canvas, contentHeight, keepTogetherRanges }) => {
      restoreReportLayout();

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
          sliceCanvas.toDataURL("image/png"),
          "PNG",
          margin,
          margin,
          imageWidth,
          sliceHeight,
        );
        sourceY = sliceEnd;
        pageIndex += 1;
      }

      pdf.save(`ClassMood_Report_${labId}_${Date.now()}.pdf`);
    })
    .catch((error) => {
      restoreReportLayout();
      console.error("Error generating PDF:", error);
      alert("ไม่สามารถสร้าง PDF ได้");
    });
}
