async function loadProducts() {
  const res = await fetch("/api/products");
  const products = await res.json();
  const select = document.getElementById("product-select");
  select.innerHTML = products
    .map(
      (p) =>
        `<option value="${p.product_id}">${p.name} - $${(p.price_cents / 100).toFixed(2)} (stock: ${p.stock})</option>`
    )
    .join("");
}

async function loadOrders() {
  const res = await fetch("/api/orders");
  const orders = await res.json();
  const tbody = document.querySelector("#orders-table tbody");
  tbody.innerHTML = orders
    .map(
      (o) =>
        `<tr><td>${o.order_id}</td><td>${o.product_id}</td><td>${o.quantity}</td><td>$${(o.total_cents / 100).toFixed(2)}</td><td>${o.status}</td><td>${o.created_at}</td></tr>`
    )
    .join("");
}

document.getElementById("order-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const product_id = parseInt(document.getElementById("product-select").value, 10);
  const quantity = parseInt(document.getElementById("quantity-input").value, 10);
  const resultEl = document.getElementById("order-result");
  resultEl.textContent = "Placing order...";
  try {
    const res = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_id, quantity }),
    });
    const data = await res.json();
    if (!res.ok) {
      resultEl.textContent = `Error: ${data.detail || res.statusText}`;
    } else {
      resultEl.textContent = `Order #${data.order_id} created, total $${(data.total_cents / 100).toFixed(2)}`;
      await loadOrders();
      await loadProducts();
    }
  } catch (err) {
    resultEl.textContent = `Request failed: ${err}`;
  }
});

document.getElementById("refresh-orders").addEventListener("click", loadOrders);

loadProducts();
loadOrders();
