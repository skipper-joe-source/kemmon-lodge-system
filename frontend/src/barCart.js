// All additions use the same stock/price checks, including consecutive scanner reads.
export function addCartProduct(cart, product, quantity = 1) {
  if (!Number.isInteger(quantity) || quantity < 1) return {cart,error:'Enter a positive whole quantity.'};
  if (product.price <= 0) return {cart,error:`${product.name} has no selling price.`};
  const previous = cart.find(item => item.productId === product.id);
  if (previous && previous.expectedPrice !== product.price) return {cart,error:`The price of ${product.name} changed. Remove it from the sale and add it again.`};
  const nextQuantity = (previous?.quantity || 0) + quantity;
  if (nextQuantity > product.stock || nextQuantity > 1000000) return {cart,error:`Not enough stock for ${product.name}. Available: ${product.stock}; already in sale: ${previous?.quantity || 0}.`};
  const item = {productId:product.id,name:product.name,quantity:nextQuantity,expectedPrice:product.price};
  return {cart:previous ? cart.map(old => old.productId === product.id ? item : old) : [...cart,item],error:'',message:`Added ${product.name}. Quantity in sale: ${nextQuantity}.`};
}
export function cartReducer(state, action) {
  switch(action.type) {
    case 'add': return addCartProduct(state.cart, action.product, action.quantity);
    case 'remove': return {cart:state.cart.filter(item=>item.productId!==action.id),error:'',message:''};
    case 'reset': return {cart:[],error:'',message:''};
    default: return state;
  }
}
