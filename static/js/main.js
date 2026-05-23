document.addEventListener("DOMContentLoaded", function () {
    const csrfTokenMeta = document.querySelector("meta[name='csrf-token']");
    const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute("content") : "";
    const semesterSets = {
        registration: {
            BS: [1, 2, 3, 4, 5, 6, 7, 8],
            MS: [1, 2, 3]
        },
        application: {
            BS: [2, 3, 4, 5, 6, 7, 8],
            MS: [2, 3]
        }
    };

    const passwordPolicyPattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,64}$/;
    const eyeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M1.5 12s3.8-6 10.5-6 10.5 6 10.5 6-3.8 6-10.5 6S1.5 12 1.5 12Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
    const eyeOffIcon = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 4.5 20.5 21" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M10.6 6.2A13.8 13.8 0 0 1 12 6c6.7 0 10.5 6 10.5 6a17.6 17.6 0 0 1-4.1 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M6.2 6.7A17.1 17.1 0 0 0 1.5 12s3.8 6 10.5 6c1.5 0 2.8-.3 4.1-.7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.7 9.7A3.3 3.3 0 0 0 12 15.3c.7 0 1.4-.2 1.9-.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    document.querySelectorAll(".password-toggle").forEach(function (button) {
        const inputGroup = button.closest(".input-group");
        const input = inputGroup ? inputGroup.querySelector(".password-field") : null;
        if (!input) {
            return;
        }

        const syncPasswordToggle = function () {
            const visible = input.getAttribute("type") === "text";
            button.innerHTML = visible ? eyeOffIcon : eyeIcon;
            button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
            button.setAttribute("title", visible ? "Hide password" : "Show password");
        };

        button.setAttribute("type", "button");
        button.classList.add("password-icon-toggle");
        syncPasswordToggle();

        button.addEventListener("click", function () {
            const visible = input.getAttribute("type") === "text";
            input.setAttribute("type", visible ? "password" : "text");
            syncPasswordToggle();
        });
    });

    document.querySelectorAll("[data-role-form]").forEach(function (formElement) {
        const roleField = formElement.querySelector("[name='role']");
        const studentFields = formElement.querySelectorAll("[data-user-group='student']");
        const hodFields = formElement.querySelectorAll("[data-user-group='hod']");

        const syncRoleFields = function () {
            const role = roleField ? roleField.value : "";
            studentFields.forEach(function (field) {
                field.style.display = role === "student" ? "" : "none";
            });
            hodFields.forEach(function (field) {
                field.style.display = role === "hod" ? "" : "none";
            });
        };

        if (roleField) {
            roleField.addEventListener("change", syncRoleFields);
            syncRoleFields();
        }
    });

    document.querySelectorAll("[data-program-semester-form]").forEach(function (formElement) {
        const programField = formElement.querySelector("[data_program_field], [data-program-field], [name='program_level']");
        const semesterField = formElement.querySelector("[data_semester_field], [data-semester-field], [name='semester']");
        const mode = formElement.dataset.semesterMode || "registration";

        const syncSemesterOptions = function () {
            if (!programField || !semesterField) {
                return;
            }
            const currentValue = semesterField.value;
            const programValue = programField.value || "BS";
            const choices = (semesterSets[mode] && semesterSets[mode][programValue]) || semesterSets.registration.BS;

            semesterField.innerHTML = "";
            choices.forEach(function (value) {
                const option = document.createElement("option");
                option.value = String(value);
                option.textContent = "Semester " + value;
                semesterField.appendChild(option);
            });

            if (choices.map(String).includes(currentValue)) {
                semesterField.value = currentValue;
            } else if (choices.length > 0) {
                semesterField.value = String(choices[0]);
            }
        };

        if (programField) {
            programField.addEventListener("change", syncSemesterOptions);
            syncSemesterOptions();
        }
    });

    document.querySelectorAll("[data-loan-form]").forEach(function (formElement) {
        const loanInput = formElement.querySelector("[data_loan_amount], [data-loan-amount], [name='loan_amount_requested']");
        const errorElement = formElement.querySelector("[data-loan-amount-error]");
        const submitButton = formElement.querySelector("button[type='submit'], input[type='submit']");

        const syncLoanAmountValidation = function () {
            if (!loanInput) {
                return;
            }
            const rawValue = (loanInput.value || "").trim();
            const value = rawValue === "" ? NaN : Number(rawValue);
            const invalid = !Number.isNaN(value) && value > 50000;
            loanInput.classList.toggle("is-invalid", invalid);
            loanInput.setCustomValidity(invalid ? "Maximum loan amount is 50,000. Please enter a valid amount." : "");
            if (errorElement) {
                errorElement.classList.toggle("d-none", !invalid);
            }
            if (submitButton) {
                submitButton.disabled = invalid;
            }
        };

        if (loanInput) {
            loanInput.addEventListener("input", syncLoanAmountValidation);
            syncLoanAmountValidation();
        }
    });

    document.querySelectorAll("form").forEach(function (formElement) {
        formElement.addEventListener("submit", function (event) {
            const submitter = event.submitter;
            if (submitter && submitter.name) {
                const decisionInput = document.createElement("input");
                decisionInput.type = "hidden";
                decisionInput.name = submitter.name;
                decisionInput.value = submitter.value;
                formElement.appendChild(decisionInput);
            }
            const submitButtons = formElement.querySelectorAll("button[type='submit'], input[type='submit']");
            submitButtons.forEach(function (button) {
                if (button.dataset.loadingBound === "true") {
                    return;
                }
                button.dataset.loadingBound = "true";
                if (button.tagName.toLowerCase() === "button") {
                    button.dataset.originalText = button.textContent;
                    button.textContent = "Please wait...";
                } else {
                    button.dataset.originalText = button.value;
                    button.value = "Please wait...";
                }
                button.disabled = true;
            });
        });
    });

    document.querySelectorAll("[data-admin-decision-form]").forEach(function (formElement) {
        const decisionField = formElement.querySelector("[name='decision']");
        const approvalFields = formElement.querySelectorAll("[data-approval-field]");
        const submitButton = formElement.querySelector("button[type='submit'], input[type='submit']");

        const syncDecisionFields = function () {
            const isApproved = decisionField && decisionField.value === "approve";
            approvalFields.forEach(function (field) {
                field.style.display = isApproved ? "" : "none";
                field.querySelectorAll("input, select, textarea").forEach(function (input) {
                    if (isApproved) {
                        input.setAttribute("required", "required");
                    } else {
                        input.removeAttribute("required");
                    }
                });
            });
        };

        if (decisionField) {
            decisionField.addEventListener("change", syncDecisionFields);
            syncDecisionFields();
        }

        formElement.addEventListener("submit", function (event) {
            const selectedDecision = decisionField ? decisionField.value : "";
            if (selectedDecision === "approve") {
                const confirmed = window.confirm("Are you sure you want to approve this loan application?");
                if (!confirmed) {
                    event.preventDefault();
                    return;
                }
            }
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.dataset.originalText = submitButton.textContent;
                submitButton.textContent = "Saving...";
            }
        });
    });

    document.querySelectorAll("[data-correction-checklist]").forEach(function (formElement) {
        const allCheckboxes = formElement.querySelectorAll("input[type='checkbox']");
        const selectAllButton = formElement.closest(".card-body").querySelector("[data-select-group='all']");
        const clearButton = formElement.closest(".card-body").querySelector("[data-select-group='none']");

        const syncCardState = function () {
            allCheckboxes.forEach(function (checkbox) {
                const card = checkbox.closest(".selection-card, .selection-row");
                if (!card) {
                    return;
                }
                card.classList.toggle("is-selected", checkbox.checked);
            });
        };

        if (selectAllButton) {
            selectAllButton.addEventListener("click", function () {
                allCheckboxes.forEach(function (checkbox) {
                    checkbox.checked = true;
                });
                syncCardState();
            });
        }

        if (clearButton) {
            clearButton.addEventListener("click", function () {
                allCheckboxes.forEach(function (checkbox) {
                    checkbox.checked = false;
                });
                syncCardState();
            });
        }

        allCheckboxes.forEach(function (checkbox) {
            checkbox.addEventListener("change", syncCardState);
        });

        syncCardState();
    });

    document.querySelectorAll(".department-selection-card input[type='checkbox']").forEach(function (checkbox) {
        const syncDepartmentCard = function () {
            const card = checkbox.closest(".department-selection-card");
            if (card) {
                card.classList.toggle("is-selected", checkbox.checked);
            }
        };

        checkbox.addEventListener("change", syncDepartmentCard);
        syncDepartmentCard();
    });

    document.querySelectorAll("[data_roll_format], [data-roll-format]").forEach(function (input) {
        input.addEventListener("input", function () {
            input.value = input.value.toUpperCase();
            const isValid = /^[A-Z]{3}\d{7}$/.test(input.value.trim());
            input.setCustomValidity(input.value && !isValid ? "Use the roll number format abc0000000." : "");
        });
    });

    document.querySelectorAll("[data_phone_format], [data-phone-format]").forEach(function (input) {
        input.addEventListener("input", function () {
            const normalized = input.value.replace(/[\s\-()]/g, "");
            const isValid = /^(?:\+92|0)3\d{9}$/.test(normalized);
            input.setCustomValidity(input.value && !isValid ? "Use 03001234567 or +923001234567." : "");
        });
    });

    document.querySelectorAll("[data_password_policy], [data-password-policy]").forEach(function (input) {
        input.addEventListener("input", function () {
            const value = input.value || "";
            const valid = passwordPolicyPattern.test(value);
            input.setCustomValidity(value && !valid ? "Password must include uppercase, lowercase, number, and special character." : "");
        });
    });

    document.querySelectorAll("input[name='iban'], input[name='student_iban'], input[name='disbursement_iban']").forEach(function (input) {
        input.addEventListener("blur", function () {
            input.value = input.value.replace(/\s+/g, "").toUpperCase();
            const isValid = /^[A-Z]{2}[0-9A-Z]{13,32}$/.test(input.value);
            input.setCustomValidity(input.value && !isValid ? "Enter a valid IBAN such as PK36SCBL0000001123456702." : "");
        });
    });

    document.querySelectorAll("[data_file_upload], [data-file-upload]").forEach(function (input) {
        const uploadCard = input.closest(".file-upload-card");
        const fileNameElement = uploadCard ? uploadCard.querySelector("[data-file-name]") : null;
        const syncFileName = function () {
            if (!fileNameElement) {
                return;
            }
            const file = input.files && input.files[0];
            fileNameElement.textContent = file ? file.name : "No file selected";
            fileNameElement.classList.toggle("has-file", Boolean(file));
        };

        input.addEventListener("change", syncFileName);
        syncFileName();
    });

    document.querySelectorAll("[data_max_size], [data-max-size]").forEach(function (input) {
        input.addEventListener("change", function () {
            const file = input.files && input.files[0];
            const maxSize = parseInt(input.dataset.maxSize || input.getAttribute("data_max_size") || "0", 10);
            if (!file || !maxSize) {
                input.setCustomValidity("");
                return;
            }
            input.setCustomValidity(file.size > maxSize ? "Selected file exceeds the allowed size limit." : "");
        });
    });

    document.querySelectorAll("[data-chatbot-form]").forEach(function (formElement) {
        const replyElement = formElement.parentElement.querySelector("[data-chatbot-reply]");
        const messageField = formElement.querySelector("[name='message']");

        formElement.querySelectorAll("[data-chatbot-suggestion]").forEach(function (button) {
            button.addEventListener("click", function () {
                if (messageField) {
                    messageField.value = button.dataset.chatbotSuggestion || "";
                    formElement.requestSubmit();
                }
            });
        });

        formElement.addEventListener("submit", function (event) {
            event.preventDefault();
            const message = messageField ? messageField.value.trim() : "";
            if (!message || !replyElement) {
                return;
            }

            replyElement.textContent = "Checking...";

            fetch("/api/chatbot", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },
                body: JSON.stringify({ message: message })
            })
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (payload) {
                    replyElement.textContent = payload.data.reply || "I can help with application status, corrections, or eligibility only.";
                })
                .catch(function () {
                    replyElement.textContent = "Chat support is not available right now. Please try again.";
                });
        });
    });

    document.querySelectorAll("[data-ai-evaluate]").forEach(function (button) {
        button.addEventListener("click", function () {
            const applicationId = button.dataset.applicationId;
            const resultElement = document.querySelector("[data-ai-result]");
            if (!applicationId || !resultElement) {
                return;
            }

            button.disabled = true;
            button.textContent = "Refreshing...";

            fetch("/api/ai/evaluate/" + applicationId, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrfToken
                }
            })
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (payload) {
                    resultElement.querySelector("[data-ai-score]").textContent = payload.data.ai_score ?? "-";
                    resultElement.querySelector("[data-ai-recommendation]").textContent = payload.data.ai_recommendation || "-";
                    resultElement.querySelector("[data-ai-explanation]").textContent = payload.data.ai_explanation || "No explanation available.";
                })
                .catch(function () {
                    resultElement.querySelector("[data-ai-explanation]").textContent = "Unable to refresh the AI suggestion right now.";
                })
                .finally(function () {
                    button.disabled = false;
                    button.textContent = "Refresh Suggestion";
                });
        });
    });

    document.querySelectorAll("table.js-sortable").forEach(function (table) {
        const headers = table.querySelectorAll("thead th");
        const body = table.querySelector("tbody");
        if (!body || headers.length === 0) {
            return;
        }
        headers.forEach(function (header, columnIndex) {
            header.style.cursor = "pointer";
            header.title = "Click to sort";
            header.addEventListener("click", function () {
                const rows = Array.from(body.querySelectorAll("tr"));
                const currentDirection = header.dataset.sortDirection === "asc" ? "asc" : "desc";
                const nextDirection = currentDirection === "asc" ? "desc" : "asc";
                headers.forEach(function (h) {
                    delete h.dataset.sortDirection;
                });
                header.dataset.sortDirection = nextDirection;
                rows.sort(function (a, b) {
                    const aText = (a.children[columnIndex] ? a.children[columnIndex].innerText : "").trim().toLowerCase();
                    const bText = (b.children[columnIndex] ? b.children[columnIndex].innerText : "").trim().toLowerCase();
                    return nextDirection === "asc" ? aText.localeCompare(bText, undefined, { numeric: true }) : bText.localeCompare(aText, undefined, { numeric: true });
                });
                rows.forEach(function (row) {
                    body.appendChild(row);
                });
            });
        });
    });

    window.setTimeout(function () {
        document.querySelectorAll(".alert").forEach(function (alertElement) {
            const alert = bootstrap.Alert.getOrCreateInstance(alertElement);
            alert.close();
        });
    }, 7000);
});
