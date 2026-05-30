const API_BASE_URL = "http://127.0.0.1:8000/api/v1";
let USER_ID = null; // Biến này giờ sẽ thay đổi linh hoạt

// --- LOGIC KIỂM TRA ĐĂNG NHẬP (Chạy đầu tiên) ---
document.addEventListener("DOMContentLoaded", () => {
    const savedUser = localStorage.getItem("USER_ID");
    if (savedUser) {
        // Đã đăng nhập
        USER_ID = savedUser;
        document.getElementById("login-screen").style.display = "none";
        document.getElementById("main-app").style.display = "flex";
        
        refreshAllRecommendationViews();
    } else {
        // Chưa đăng nhập
        document.getElementById("login-screen").style.display = "flex";
        document.getElementById("main-app").style.display = "none";
    }
});

// --- HÀM XỬ LÝ NÚT ĐĂNG NHẬP ---
async function handleLogin() {
    const u = document.getElementById("usernameInput").value.trim();
    const p = document.getElementById("passwordInput").value.trim();
    const errorTxt = document.getElementById("login-error");

    if (!u || !p) {
        errorTxt.innerText = "Vui lòng nhập đủ thông tin!";
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p })
        });
        const data = await response.json();

        if (data.success) {
            alert("Đăng nhập thành công!");
            localStorage.setItem("USER_ID", data.user_id);
            window.location.reload(); // Tải lại trang để load dữ liệu của user đó
        } else {
            errorTxt.innerText = data.message; // Báo lỗi sai mật khẩu
        }
    } catch (error) {
        console.error("Lỗi đăng nhập:", error);
    }
}

// --- HÀM XỬ LÝ ĐĂNG XUẤT ---
function handleLogout() {
    localStorage.removeItem("USER_ID");
    window.location.reload();
} 

let isLoginMode = true;

function toggleAuthMode() {
    isLoginMode = !isLoginMode;
    const title = document.getElementById("form-title");
    const authBtn = document.getElementById("auth-btn");
    const rePass = document.getElementById("repasswordInput");
    const toggleLink = document.getElementById("toggle-auth-link");
    const errorTxt = document.getElementById("login-error");

    errorTxt.innerText = "";
    document.getElementById("usernameInput").value = "";
    document.getElementById("passwordInput").value = "";
    document.getElementById("repasswordInput").value = "";

    if (isLoginMode) {
        title.innerText = "Đăng Nhập";
        authBtn.innerText = "Đăng Nhập";
        authBtn.setAttribute("onclick", "handleLogin()");
        rePass.style.display = "none";
        toggleLink.innerText = "Chưa có tài khoản? Đăng ký ngay";
    } else {
        title.innerText = "Đăng Ký";
        authBtn.innerText = "Đăng Ký";
        authBtn.setAttribute("onclick", "handleRegister()");
        rePass.style.display = "block";
        toggleLink.innerText = "Đã có tài khoản? Đăng nhập";
    }
}

async function handleRegister() {
    const u = document.getElementById("usernameInput").value.trim();
    const p = document.getElementById("passwordInput").value.trim();
    const rp = document.getElementById("repasswordInput").value.trim();
    const errorTxt = document.getElementById("login-error");

    if (!u || !p || !rp) {
        errorTxt.innerText = "Vui lòng nhập đủ thông tin!";
        return;
    }
    if (p !== rp) {
        errorTxt.innerText = "Mật khẩu không khớp!";
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p })
        });
        const data = await response.json();

        if (data.success) {
            alert("Đăng ký thành công! Vui lòng đăng nhập.");
            toggleAuthMode();
        } else {
            errorTxt.innerText = data.message;
        }
    } catch (error) {
        console.error("Lỗi đăng ký:", error);
    }
}

const HISTORY_FEEDBACK_PREFIX = "history_feedback";

function getHistoryFeedbackKey(trackId) {
    return `${HISTORY_FEEDBACK_PREFIX}:${USER_ID || "guest"}:${trackId}`;
}

function getHistoryFeedback(trackId) {
    return localStorage.getItem(getHistoryFeedbackKey(trackId)) || "";
}

function toggleHistoryFeedback(trackId, feedback, button) {
    const key = getHistoryFeedbackKey(trackId);
    const currentFeedback = localStorage.getItem(key);
    const nextFeedback = currentFeedback === feedback ? "" : feedback;

    if (nextFeedback) {
        localStorage.setItem(key, nextFeedback);
    } else {
        localStorage.removeItem(key);
    }

    const actions = button.closest(".history-actions");
    actions.querySelectorAll(".feedback-btn").forEach((item) => {
        item.classList.toggle("selected", item.dataset.feedback === nextFeedback);
    });
}

function clearHistoryFeedbackForCurrentUser() {
    const prefix = `${HISTORY_FEEDBACK_PREFIX}:${USER_ID || "guest"}:`;
    Object.keys(localStorage).forEach((key) => {
        if (key.startsWith(prefix)) {
            localStorage.removeItem(key);
        }
    });
}

async function refreshAllRecommendationViews() {
    await loadHistory(false);
    await Promise.all([
        loadHistoryRecommendations(),
        loadMelodyRecommendations(),
        loadHybridRecommendations()
    ]);
}

// 1. Cập nhật hàm tạo HTML (Thêm tham số isHistory)
function createTrackHTML(track, index, isHistory = false) {
    const colors = ["#4facfe", "#f093fb", "#43e97b", "#fa709a", "#a18cd1"];
    const color = colors[index % colors.length];
    
    // Nếu là bài hát trong lịch sử thì hiện nút X, gọi hàm deleteHistory
    let actionsHtml = '';
    if (isHistory && track.track_id) {
        const feedback = getHistoryFeedback(track.track_id);
        const likeClass = feedback === "like" ? " selected" : "";
        const dislikeClass = feedback === "dislike" ? " selected" : "";
        actionsHtml = `
            <div class="history-actions">
                <button class="feedback-btn${likeClass}" data-feedback="like" onclick="toggleHistoryFeedback('${track.track_id}', 'like', this)" title="Like">&#128077;</button>
                <button class="feedback-btn${dislikeClass}" data-feedback="dislike" onclick="toggleHistoryFeedback('${track.track_id}', 'dislike', this)" title="Dislike">&#128078;</button>
                <button class="delete-btn" onclick="deleteHistory('${track.track_id}')" title="Xóa khỏi lịch sử">✖</button>
            </div>
        `;
    }
    let desc = track.artist || track.genre || 'Unknown';
    if (track.hybrid_score !== undefined) {
        desc += ` <span style="color: #4facfe; font-weight: bold;">(Độ phù hợp: ${(track.hybrid_score * 100).toFixed(0)}%)</span>`;
    }

    return `
        <div class="track-item">
            <div class="track-left">
                <div class="track-cover" style="background: linear-gradient(135deg, ${color} 0%, #333 100%);">
                    🎶
                </div>
                <div class="track-info">
                    <h4>${track.name || track['Tên bài hát']}</h4>
                    <p>${track.artist || track.genre || track['Độ ưu thích'] || track['Độ tương đồng'] || 'Unknown'}</p>
                </div>
            </div>
            ${actionsHtml}
        </div>
    `;
}

// 2. Viết thêm hàm Xóa Lịch Sử
async function deleteHistory(trackId) {
    try {
        const response = await fetch(`${API_BASE_URL}/users/${USER_ID}/history/${trackId}`, { method: 'DELETE' });
        if (!response.ok) {
            throw new Error("Không thể xóa bài hát khỏi lịch sử.");
        }

        localStorage.removeItem(getHistoryFeedbackKey(trackId));
        
        // Sau khi xóa xong, tải lại lịch sử và cả 3 thuật toán.
        await refreshAllRecommendationViews();
    } catch (error) {
        console.error("Lỗi xóa lịch sử:", error);
    }
}

// --- Hàm Xóa Toàn Bộ Lịch Sử ---
async function clearAllHistory() {
    // Hiện bảng hỏi xác nhận để tránh người dùng bấm nhầm
    if (!confirm("Bạn có chắc chắn muốn reset toàn bộ lịch sử nghe nhạc không?")) {
        return; 
    }

    try {
        const response = await fetch(`${API_BASE_URL}/users/${USER_ID}/history/clear`, { method: 'DELETE' });
        if (!response.ok) {
            throw new Error("Không thể xóa toàn bộ lịch sử.");
        }

        clearHistoryFeedbackForCurrentUser();
        
        // Sau khi xóa xong, load lại toàn bộ giao diện và 3 khối gợi ý.
        await refreshAllRecommendationViews();
    } catch (error) {
        console.error("Lỗi xóa toàn bộ lịch sử:", error);
    }
}

// 3. Sửa nhẹ hàm loadHistory (truyền thêm true vào createTrackHTML)
async function loadHistory(refreshRecommendations = true) {
    try {
        const response = await fetch(`${API_BASE_URL}/users/${USER_ID}/history`, { cache: "no-store" });
        const data = await response.json();
        const historyList = document.getElementById("history-list");
        
        historyList.innerHTML = ""; 

        if (data.history.length === 0) {
            historyList.innerHTML = '<p class="loading" style="color: white;">Chưa có lịch sử nghe nhạc.</p>';
            document.getElementById("melody-recs").innerHTML = '<p class="loading">Hãy nghe 1 bài hát để nhận gợi ý nhé.</p>';
            document.getElementById("hybrid-recs").innerHTML = '<p class="loading">Hãy nghe 1 bài hát để nhận gợi ý nhé.</p>';
            return;
        }

        data.history.forEach((track, index) => {
            // Thêm chữ "true" để báo cho hàm biết đây là lịch sử -> Hiện nút X
            historyList.innerHTML += createTrackHTML(track, index, true);
        });

        if (refreshRecommendations) {
            loadMelodyRecommendations();
            loadHybridRecommendations();
        }
    } catch (error) {
        console.error("Lỗi tải lịch sử:", error);
    }
}

// 2. Fetch Gợi ý theo ALS (Lịch sử)
async function loadHistoryRecommendations() {
    const recList = document.getElementById("history-recs");
    recList.innerHTML = '<p class="loading">Đang tìm bài hát tương đồng...</p>';

    try {
        const response = await fetch(`${API_BASE_URL}/recommendations/history/${USER_ID}`, { cache: "no-store" });
        const data = await response.json();
        
        recList.innerHTML = ""; // Xóa chữ loading cũ
        
        // Nếu API có gửi kèm thông báo (Cần nghe thêm X bài / Gợi ý riêng cho bạn)
        if (data.message) {
            recList.innerHTML += `<p class="loading" style="color: #ff9800; font-weight: bold; margin-bottom: 12px;">${data.message}</p>`;
        }

        // Vẽ danh sách bài hát (Dù là Top Thịnh Hành hay ALS trả về)
        if (data.recommendations && data.recommendations.length > 0) {
            data.recommendations.slice(0, 5).forEach((track, index) => {
                recList.innerHTML += createTrackHTML(track, index + 2); 
            });
        } else {
            // Đề phòng trường hợp lỗi thật sự, mảng bị rỗng
            recList.innerHTML += '<p class="loading">Chưa có dữ liệu gợi ý.</p>';
        }
        
    } catch (error) {
        console.error("Lỗi tải Gợi ý:", error);
    }
}

// 3. Fetch Gợi ý theo KNN (Giai điệu)
async function loadMelodyRecommendations() {
    const melodyTitle = document.getElementById("melody-title");
    if (melodyTitle) {
        melodyTitle.innerText = "Top 5 gợi ý theo giai điệu";
    }

    try {
        const response = await fetch(`${API_BASE_URL}/recommendations/melody/${USER_ID}`, { cache: "no-store" });
        const data = await response.json();
        const recList = document.getElementById("melody-recs");
        
        if (data.message || !data.recommendations || data.recommendations.length === 0) {
            recList.innerHTML = `<p class="loading">${data.message || "Không tìm thấy bài hát tương tự."}</p>`;
            return;
        }

        recList.innerHTML = "";
        data.recommendations.forEach((track, index) => {
            recList.innerHTML += createTrackHTML(track, index + 4);
        });
    } catch (error) {
        console.error("Lỗi tải KNN:", error);
    }
}


// --- LOGIC THANH TÌM KIẾM ---
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
let debounceTimer; // Biến dùng để trì hoãn việc gọi API

// Lắng nghe sự kiện người dùng gõ phím
searchInput.addEventListener('input', (e) => {
    clearTimeout(debounceTimer); // Xóa bộ đếm cũ nếu người dùng vẫn đang gõ
    const query = e.target.value.trim();

    // Nếu xóa trắng thanh search thì ẩn list
    if (query.length === 0) {
        searchResults.classList.remove('active');
        return;
    }

    // Đợi 300ms sau khi người dùng NGỪNG GÕ mới gọi API
    debounceTimer = setTimeout(async () => {
        try {
            // Encode chuỗi để tránh lỗi khi gõ dấu tiếng Việt
            const response = await fetch(`${API_BASE_URL}/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            
            renderSearchResults(data.results);
        } catch (error) {
            console.error("Lỗi tìm kiếm:", error);
        }
    }, 300); 
});

// Hàm hiển thị danh sách kết quả
function renderSearchResults(results) {
    searchResults.innerHTML = '';
    
    if (results.length === 0) {
        searchResults.innerHTML = '<div class="search-item" style="cursor:default;"><span>Không tìm thấy bài hát nào</span></div>';
    } else {
        results.forEach(track => {
            const item = document.createElement('div');
            item.className = 'search-item';
            item.innerHTML = `
                <strong>${track.name}</strong>
                <span>${track.artist || 'Unknown'}</span>
            `;
            
            // Xử lý khi click vào 1 bài hát trong danh sách tìm kiếm
            item.addEventListener('click', async () => {
                searchInput.value = ''; // Reset thanh tìm kiếm sau khi chọn
                searchResults.classList.remove('active'); 
                
                try {
                    // 1. GỌI API THÊM VÀO LỊCH SỬ (Và bắt buộc phải đợi xong bằng 'await')
                    const response = await fetch(`${API_BASE_URL}/users/${USER_ID}/history/${track.track_id}`, { method: 'POST' });
                    if (!response.ok) {
                        throw new Error("Không thể thêm bài hát vào lịch sử.");
                    }
                    
                    document.getElementById('melody-recs').innerHTML = '<p class="loading">Đang phân tích âm thanh...</p>';

                    // 2. SAU KHI GHI XONG MỚI ĐỌC DỮ LIỆU
                    await refreshAllRecommendationViews();

                } catch (error) {
                    console.error("Lỗi thêm vào lịch sử:", error);
                }
            });
            
            searchResults.appendChild(item);
        });
    }
    // Hiện danh sách lên
    searchResults.classList.add('active');
}

// Ẩn danh sách tìm kiếm khi click chuột ra ngoài vùng khác trên trang web
document.addEventListener('click', (e) => {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
        searchResults.classList.remove('active');
    }
});

// --- HÀM GỌI API HYBRID TỰ ĐỘNG ---
async function loadHybridRecommendations() {
    const recList = document.getElementById("hybrid-recs");
    recList.innerHTML = '<p class="loading">Đang tìm bài hát tương đồng...</p>';
    
    try {
        const response = await fetch(`${API_BASE_URL}/recommendations/hybrid/${USER_ID}`, { cache: "no-store" });
        const data = await response.json();
        
        if (data.message || !data.recommendations || data.recommendations.length === 0) {
            recList.innerHTML = `<p class="loading">${data.message || "Chưa có dữ liệu."}</p>`;
            return;
        }

        recList.innerHTML = "";
        data.recommendations.forEach((track, index) => {
            recList.innerHTML += createTrackHTML(track, index + 7);
        });
    } catch (error) {
        console.error("Lỗi tải Hybrid:", error);
    }
}
