document.addEventListener("DOMContentLoaded", () => {
    fetchStats();
    fetchLeaderboard();
    fetchRecent();

    // Handle Form Submission
    document.getElementById('claimForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('submitBtn');
        const statusText = document.getElementById('formStatus');
        
        btn.innerText = "Submitting...";
        btn.disabled = true;

        const data = {
            name: document.getElementById('name').value,
            instagram_id: document.getElementById('instagram').value,
            amount: document.getElementById('amount').value,
            message: document.getElementById('message').value
        };

        try {
            const response = await fetch('/api/submit_claim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await response.json();
            
            if(result.status === 'success') {
                statusText.style.color = "green";
                statusText.innerText = "Thank you! Your donation is pending admin verification.";
                document.getElementById('claimForm').reset();
            } else {
                statusText.style.color = "red";
                statusText.innerText = "Error submitting claim.";
            }
        } catch (err) {
            statusText.style.color = "red";
            statusText.innerText = "Network error. Try again.";
        }
        
        btn.innerText = "Submit Details";
        btn.disabled = false;
    });
});

async function fetchStats() {
    const res = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('totalAmount').innerText = data.total_amount.toLocaleString('en-IN');
    document.getElementById('totalDonors').innerText = data.total_donors;
}

async function fetchLeaderboard() {
    const res = await fetch('/api/leaderboard');
    const data = await res.json();
    const tbody = document.getElementById('leaderboardBody');
    tbody.innerHTML = '';
    
    data.forEach((donor, index) => {
        let tr = document.createElement('tr');
        tr.innerHTML = `
            <td>#${index + 1}</td>
            <td><strong>${donor.name}</strong></td>
            <td>${donor.instagram_id || '-'}</td>
            <td>₹${donor.amount.toLocaleString('en-IN')}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function fetchRecent() {
    const res = await fetch('/api/recent');
    const data = await res.json();
    const list = document.getElementById('recentList');
    list.innerHTML = '';
    
    data.forEach(donor => {
        let li = document.createElement('li');
        li.style.padding = "10px 0";
        li.style.borderBottom = "1px solid #eee";
        li.innerHTML = `<strong>${donor.instagram_id || donor.name}</strong> donated <span style="color: #50E3C2; font-weight: bold;">₹${donor.amount.toLocaleString('en-IN')}</span>`;
        list.appendChild(li);
    });
}