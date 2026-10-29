(function () {
    function updateSections() {
        const examField = document.getElementById("id_exam");
        const sectionField = document.getElementById("id_section");
        if (!examField || !sectionField) return;

        const examId = examField.value;
        let selectedAvailable = false;
        Array.from(sectionField.options).forEach((option) => {
            const visible = !option.value || (examId && option.dataset.examId === examId);
            option.hidden = !visible;
            if (visible && option.selected) selectedAvailable = true;
        });

        if (!selectedAvailable) sectionField.value = "";
        sectionField.disabled = !examId;
    }

    document.addEventListener("DOMContentLoaded", function () {
        const examField = document.getElementById("id_exam");
        if (!examField) return;
        examField.addEventListener("change", updateSections);
        updateSections();
    });
})();
